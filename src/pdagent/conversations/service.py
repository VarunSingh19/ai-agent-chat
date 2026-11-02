"""Conversation turn orchestration implementing the 12-step pipeline (Architecture.md §7a)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.agent.canonical import CanonicalMessage, ToolCall
from pdagent.agent.context import build_prompt_bundle
from pdagent.agent.loop import run_agent_turn_loop
from pdagent.agent.providers.base import ProviderGateway
from pdagent.agent.router import classify_and_route
from pdagent.audit.models import OrgSettingsRow
from pdagent.auth.principal import Principal
from pdagent.conversations.repo import ConversationRepo, ConversationRow, MessageRow
from pdagent.conversations.summary import build_rolling_summary
from pdagent.core.errors import AppError, ErrorCode
from pdagent.handoff.emergency import check_emergency_message
from pdagent.handoff.notify import StaffAlertDispatcher
from pdagent.handoff.service import HandoffService
from pdagent.knowledge.ingest.embed import EmbeddingClient
from pdagent.knowledge.retrieve import retrieve_knowledge_chunks
from pdagent.limits.ratelimit import SlidingWindowRateLimiter
from pdagent.limits.spend import SpendGuard
from pdagent.mcp_server.pdapi_client import PropertyDekApiClient
from pdagent.mcp_server.tools_read import dispatch_read_tool
from pdagent.tools.confirm import ConfirmationService
from pdagent.tools.registry import resolve_tools_for_principal


class ConversationService:
    """Executes the 12-step turn pipeline with pre-LLM emergency checks, spend reservations, and
    SSE.
    """

    @staticmethod
    async def open_or_resume(
        session: AsyncSession,
        *,
        principal: Principal,
        channel: str = "web",
        property_id: UUID | None = None,
    ) -> ConversationRow:
        if property_id is not None and not principal.can_access_property(property_id):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Property Not Found",
                detail="The specified property was not found.",
                status_code=404,
            )
        resolved_prop = property_id or (
            principal.property_ids[0] if principal.property_ids else None
        )
        return await ConversationRepo.create_or_resume(
            session,
            org_id=principal.org_id,
            user_id=principal.user_id,
            channel=channel,
            property_id=resolved_prop,
            unit_id=principal.unit_id,
        )

    @staticmethod
    async def list_history(
        session: AsyncSession,
        *,
        principal: Principal,
        conversation_id: UUID,
        after_seq: int = 0,
    ) -> list[MessageRow]:
        conv = await ConversationRepo.get_for_principal(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        if conv is None or not _can_view_conversation(principal, conv):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Conversation Not Found",
                detail="The requested conversation was not found.",
                status_code=404,
            )
        return await ConversationRepo.list_messages(
            session,
            org_id=principal.org_id,
            conversation_id=conversation_id,
            after_seq=after_seq,
        )

    @staticmethod
    async def handle_user_turn(
        session: AsyncSession,
        *,
        principal: Principal,
        conversation_id: UUID,
        user_content: str,
        idempotency_key: str,
        gateway: ProviderGateway,
        rate_limiter: SlidingWindowRateLimiter,
        spend_guard: SpendGuard,
        pdapi: PropertyDekApiClient,
        notifier: StaffAlertDispatcher,
        embedder: EmbeddingClient | None = None,
        unhelpful_previous: bool = False,
    ) -> list[tuple[str, dict[str, object], str | None]]:
        """Execute a complete user turn and return the ordered list of SSE events."""
        conv = await ConversationRepo.get_for_principal(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        if conv is None or not _can_view_conversation(principal, conv):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Conversation Not Found",
                detail="The requested conversation was not found.",
                status_code=404,
            )

        # Step 1: Idempotency check (24 h deduplication)
        cached_msg = await ConversationRepo.find_by_idempotency_key(
            session,
            org_id=principal.org_id,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
        )
        if cached_msg is not None:
            return _build_sse_events_from_message(cached_msg)

        org_cfg = await _get_org_settings(session, principal.org_id)

        # Step 2: Persist incoming user message
        await ConversationRepo.append_message(
            session,
            org_id=principal.org_id,
            conversation_id=conversation_id,
            sender_role="user",
            content=user_content,
        )

        # Step 3: While conversation.status == 'staff', store user message and notify staff,
        # NEVER call a model (Architecture.md §7d, Phases.md Phase 6 exit criterion).
        if conv.status == "staff":
            await notifier.notify_staff(
                org_id=principal.org_id,
                conversation_id=conversation_id,
                reason="staff_thread_message",
                is_emergency=False,
            )
            return [
                (
                    "handoff",
                    {"state": "staff", "conversation_id": str(conversation_id)},
                    str(conv.next_seq),
                )
            ]

        # Step 4: Deterministic emergency rules BEFORE any model or Redis call (Rules.md §1 Rule 6).
        emg = check_emergency_message(user_content, emergency_phone=org_cfg.emergency_phone)
        if emg.matched:
            await HandoffService.escalate_conversation(
                session,
                principal=principal,
                conversation_id=conversation_id,
                reason="emergency",
                is_emergency=True,
                matched_rule=emg.rule_id,
                timeout_seconds=org_cfg.handoff_timeout_seconds,
                notifier=notifier,
            )
            emg_msg = await ConversationRepo.append_message(
                session,
                org_id=principal.org_id,
                conversation_id=conversation_id,
                sender_role="assistant",
                content=emg.safety_reply,
                route="emergency",
                idempotency_key=idempotency_key,
            )
            return [
                ("message.start", {"id": str(emg_msg.id), "seq": emg_msg.seq}, str(emg_msg.seq)),
                (
                    "handoff",
                    {
                        "state": "waiting",
                        "reason": "emergency",
                        "rule_id": emg.rule_id,
                    },
                    str(emg_msg.seq),
                ),
                ("token", {"text": emg.safety_reply}, str(emg_msg.seq)),
                (
                    "message.end",
                    {
                        "id": str(emg_msg.id),
                        "seq": emg_msg.seq,
                        "usage_public": {"degraded": False, "emergency": True},
                    },
                    str(emg_msg.seq),
                ),
            ]

        # Step 5: Rate limiting (after emergency check so emergencies are never rate-limited)
        await rate_limiter.check_user_and_org(principal.org_id, principal.user_id)

        # Two-unhelpful escalation trigger (Architecture.md §7a & §7d)
        new_unhelpful = conv.unhelpful_count + (1 if unhelpful_previous else 0)
        if new_unhelpful >= 2:
            await HandoffService.escalate_conversation(
                session,
                principal=principal,
                conversation_id=conversation_id,
                reason="two_unhelpful_turns",
                is_emergency=False,
                timeout_seconds=org_cfg.handoff_timeout_seconds,
                notifier=notifier,
            )
            unhelpful_reply = (
                "I'm sorry those answers weren't helpful. I have connected this thread "
                "to your property management team so a staff member can assist you directly."
            )
            msg_row = await ConversationRepo.append_message(
                session,
                org_id=principal.org_id,
                conversation_id=conversation_id,
                sender_role="assistant",
                content=unhelpful_reply,
                route="handoff",
                idempotency_key=idempotency_key,
            )
            return _build_sse_events_from_message(msg_row, handoff_state="waiting")

        # Step 6: Deterministic rule routing first (Architecture.md §7a)
        route_decision = classify_and_route(user_content)
        if route_decision.canned_response is not None:
            handoff_state: str | None = None
            if route_decision.immediate_handoff_reason is not None:
                await HandoffService.escalate_conversation(
                    session,
                    principal=principal,
                    conversation_id=conversation_id,
                    reason=route_decision.immediate_handoff_reason,
                    is_emergency=False,
                    timeout_seconds=org_cfg.handoff_timeout_seconds,
                    notifier=notifier,
                )
                handoff_state = "waiting"
            canned_msg = await ConversationRepo.append_message(
                session,
                org_id=principal.org_id,
                conversation_id=conversation_id,
                sender_role="assistant",
                content=route_decision.canned_response,
                route=route_decision.route,
                idempotency_key=idempotency_key,
            )
            return _build_sse_events_from_message(canned_msg, handoff_state=handoff_state)

        # Step 7: Spend reservation before model call (Architecture.md §7e)
        primary_spec = gateway.catalog.get_spec("anthropic", route_decision.route)
        max_res_usd = primary_spec.max_reservation_usd(
            estimated_input_tokens=2000, max_output_tokens=400
        )
        reservation = await spend_guard.reserve(
            org_id=principal.org_id,
            user_id=principal.user_id,
            max_cost_usd=max_res_usd,
            org_daily_cap_usd=org_cfg.daily_budget_usd,
            user_daily_cap_usd=org_cfg.user_daily_budget_usd,
        )

        if not reservation.allowed and route_decision.intent != "faq":
            degraded_text = (
                "The assistant's daily usage budget has been reached. "
                "Please use the PropertyDek Maintenance Request Form or contact your "
                "property office."
            )
            deg_msg = await ConversationRepo.append_message(
                session,
                org_id=principal.org_id,
                conversation_id=conversation_id,
                sender_role="assistant",
                content=degraded_text,
                route="small",
                degraded=True,
                idempotency_key=idempotency_key,
            )
            return _build_sse_events_from_message(
                deg_msg, extra_code=ErrorCode.BUDGET_DEGRADED.value
            )

        effective_route = "small" if reservation.degraded else route_decision.route
        effective_max_tokens = 150 if not reservation.allowed else 400

        # Step 8: Retrieve knowledge chunks & build cache-stable prompt (Architecture.md §7b, §7c)
        retrieval = await retrieve_knowledge_chunks(
            session, principal=principal, query=user_content, top_k=5, embedder=embedder
        )
        allowed_tools = resolve_tools_for_principal(
            principal, org_enabled_tools=org_cfg.enabled_tools
        )
        prompt_bundle = build_prompt_bundle(
            tools=allowed_tools,
            tone=org_cfg.tone,
            enabled_tools=org_cfg.enabled_tools,
            rolling_summary=conv.rolling_summary,
            retrieved_chunks=retrieval.chunks,
            user_message=user_content,
            forbidden_before_breakpoint=(
                str(principal.org_id),
                str(principal.user_id),
                str(conversation_id),
                user_content if len(user_content) > 12 else "",
            ),
        )

        prior_rows = await ConversationRepo.list_messages(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        canonical_history = [
            CanonicalMessage(
                role="assistant" if r.sender_role in ("assistant", "staff") else "user",
                content=r.content,
            )
            for r in prior_rows[-6:]
        ]

        async def _exec_read(tool_name: str, args: dict[str, object]) -> dict[str, object]:
            return await dispatch_read_tool(
                tool_name,
                args,
                principal=principal,
                pdapi=pdapi,
                session=session,
            )

        async def _create_conf(tc: ToolCall) -> dict[str, object]:
            return await ConfirmationService.create_pending_card(
                session,
                principal=principal,
                conversation_id=conversation_id,
                tool_name=tc.name,
                arguments=tc.arguments,
            )

        # Step 9: Run bounded agent loop
        try:
            loop_res = await run_agent_turn_loop(
                gateway=gateway,
                prompt=prompt_bundle,
                initial_messages=canonical_history,
                route=effective_route,
                execute_read_tool=_exec_read,
                create_write_confirmation=_create_conf,
                max_output_tokens=effective_max_tokens,
            )
        except AppError as exc:
            await spend_guard.settle(reservation, 0.0)
            if exc.code == ErrorCode.PROVIDER_UNAVAILABLE:
                fallback_text = (
                    "Our AI providers are temporarily unavailable. You can submit a "
                    "request directly "
                    "using the PropertyDek Request Form, or I can connect you with property staff."
                )
                fb_msg = await ConversationRepo.append_message(
                    session,
                    org_id=principal.org_id,
                    conversation_id=conversation_id,
                    sender_role="assistant",
                    content=fallback_text,
                    route=effective_route,
                    degraded=True,
                    idempotency_key=idempotency_key,
                )
                return _build_sse_events_from_message(
                    fb_msg, extra_code=ErrorCode.PROVIDER_UNAVAILABLE.value
                )
            raise

        await spend_guard.settle(reservation, loop_res.cost_usd)

        sources_payload: list[dict[str, object]] = [
            {
                "document_id": c.document_id,
                "title": c.title,
                "section": c.heading_path,
                "page": c.page_number,
            }
            for c in retrieval.chunks
        ]

        assistant_msg = await ConversationRepo.append_message(
            session,
            org_id=principal.org_id,
            conversation_id=conversation_id,
            sender_role="assistant",
            content=loop_res.assistant_text or "How else can I assist you?",
            model=loop_res.model,
            provider=loop_res.provider,
            route=loop_res.route,
            input_tokens=loop_res.input_tokens,
            output_tokens=loop_res.output_tokens,
            cache_read_tokens=loop_res.cache_read_tokens,
            reasoning_tokens=loop_res.reasoning_tokens,
            cost_usd=loop_res.cost_usd,
            latency_ms=loop_res.latency_ms,
            failover=loop_res.failover,
            degraded=reservation.degraded or retrieval.degraded_retrieval,
            sources=sources_payload,
            idempotency_key=idempotency_key,
        )

        # Step 12: Update rolling summary from messages only (Rules.md §5 LLM05)
        updated_rows = [*prior_rows, assistant_msg]
        new_summary = build_rolling_summary(updated_rows)
        await ConversationRepo.update_rolling_summary_and_unhelpful(
            session,
            org_id=principal.org_id,
            conversation_id=conversation_id,
            rolling_summary=new_summary,
            unhelpful_count=new_unhelpful,
        )

        return _build_sse_events_from_message(
            assistant_msg,
            tool_names=loop_res.tool_names_called,
            confirmation_card=loop_res.confirmation_card,
            error_code=loop_res.error_code,
        )


def _can_view_conversation(principal: Principal, conv: ConversationRow) -> bool:
    if principal.role == "fbc_operator":
        return False
    if principal.role == "tenant":
        return conv.user_id == principal.user_id
    if principal.role == "pm_member":
        return principal.can_access_property(conv.property_id)
    return principal.role == "org_admin"


async def _get_org_settings(session: AsyncSession, org_id: UUID) -> OrgSettingsRow:
    stmt = select(OrgSettingsRow).where(OrgSettingsRow.org_id == org_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    default_row = OrgSettingsRow(org_id=org_id)
    session.add(default_row)
    await session.flush()
    return default_row


def _build_sse_events_from_message(
    msg: MessageRow,
    *,
    tool_names: list[str] | None = None,
    confirmation_card: dict[str, object] | None = None,
    handoff_state: str | None = None,
    error_code: str | None = None,
    extra_code: str | None = None,
) -> list[tuple[str, dict[str, object], str | None]]:
    seq_str = str(msg.seq)
    events: list[tuple[str, dict[str, object], str | None]] = [
        ("message.start", {"id": str(msg.id), "seq": msg.seq}, seq_str)
    ]
    for src in msg.sources_json:
        events.append(("source", dict(src), seq_str))
    for t_name in tool_names or []:
        events.append(("tool.start", {"name": t_name}, seq_str))
    if confirmation_card is not None:
        events.append(("confirm.card", confirmation_card, seq_str))
    if handoff_state is not None:
        events.append(("handoff", {"state": handoff_state}, seq_str))

    for word_idx, word in enumerate(msg.content.split(" ")):
        piece = word if word_idx == 0 else f" {word}"
        events.append(("token", {"text": piece}, seq_str))

    if error_code is not None:
        events.append(("error", {"code": error_code}, seq_str))

    usage_pub: dict[str, object] = {
        "degraded": msg.degraded,
        "failover": msg.failover,
    }
    if extra_code is not None:
        usage_pub["code"] = extra_code

    events.append(
        (
            "message.end",
            {"id": str(msg.id), "seq": msg.seq, "usage_public": usage_pub},
            seq_str,
        )
    )
    return events
