"""Handoff escalation and timeout service (Phase 6, Architecture.md §7d)."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.audit.service import AuditService
from pdagent.auth.principal import Principal
from pdagent.core.errors import AppError, ErrorCode
from pdagent.core.ids import new_id, utc_now
from pdagent.core.rls import verify_rls_context
from pdagent.handoff.notify import StaffAlertDispatcher
from pdagent.handoff.states import HandoffRow


class HandoffService:
    """Manages escalation to `waiting`, emergency alerts, and timeout fallback forms."""

    @staticmethod
    async def escalate_conversation(
        session: AsyncSession,
        *,
        principal: Principal,
        conversation_id: UUID,
        reason: str,
        is_emergency: bool = False,
        matched_rule: str | None = None,
        timeout_seconds: int = 300,
        notifier: StaffAlertDispatcher | None = None,
    ) -> HandoffRow:
        """Transition conversation to `waiting`, insert `HandoffRow`, and notify staff."""
        await verify_rls_context(session)
        conv_res = await session.execute(
            text(
                """
                SELECT id, user_id, property_id, status
                FROM conversations
                WHERE id = :conv_id AND org_id = :org_id
                """
            ),
            {"conv_id": conversation_id, "org_id": principal.org_id},
        )
        conv_row = conv_res.first()
        if conv_row is None:
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Conversation Not Found",
                detail="The requested conversation was not found.",
                status_code=404,
            )
        if principal.role == "tenant" and UUID(str(conv_row[1])) != principal.user_id:
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Conversation Not Found",
                detail="The requested conversation was not found.",
                status_code=404,
            )

        now = utc_now()
        await session.execute(
            text(
                """
                UPDATE conversations
                SET status = 'waiting', updated_at = :now_utc
                WHERE id = :conv_id AND org_id = :org_id
                """
            ),
            {"now_utc": now, "conv_id": conversation_id, "org_id": principal.org_id},
        )

        handoff = HandoffRow(
            id=new_id(),
            org_id=principal.org_id,
            conversation_id=conversation_id,
            reason=reason,
            is_emergency=is_emergency,
            matched_rule=matched_rule,
            state="waiting",
            timeout_at=now + timedelta(seconds=timeout_seconds),
            created_at=now,
        )
        session.add(handoff)
        await session.flush()

        await AuditService.record(
            session,
            principal=principal,
            action="handoff.escalated",
            target_type="conversation",
            target_id=str(conversation_id),
            outcome="waiting",
            metadata={
                "reason": reason,
                "is_emergency": is_emergency,
                "matched_rule": matched_rule,
            },
        )

        if notifier is not None:
            await notifier.notify_staff(
                org_id=principal.org_id,
                conversation_id=conversation_id,
                reason=reason,
                is_emergency=is_emergency,
                matched_rule=matched_rule,
            )
        return handoff

    @staticmethod
    async def process_expired_waiting_handoffs(
        session: AsyncSession,
        *,
        org_id: UUID,
    ) -> int:
        """Find `waiting` handoffs past `timeout_at` and post the fallback request form exactly
        once.
        """
        await verify_rls_context(session)
        now = utc_now()
        stmt = select(HandoffRow).where(
            HandoffRow.org_id == org_id,
            HandoffRow.state == "waiting",
            HandoffRow.outcome.is_(None),
            HandoffRow.timeout_at <= now,
        )
        expired_rows = list((await session.execute(stmt)).scalars().all())
        count = 0
        for row in expired_rows:
            upd = await session.execute(
                update(HandoffRow)
                .where(
                    HandoffRow.id == row.id,
                    HandoffRow.org_id == org_id,
                    HandoffRow.outcome.is_(None),
                )
                .values(outcome="timeout_form")
                .returning(HandoffRow.id)
            )
            if upd.first() is not None:
                count += 1
        return count
