"""Repository for `org_settings` and usage metrics aggregation (Phase 10)."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.audit.models import OrgSettingsRow
from pdagent.conversations.repo import ConversationRow, MessageRow
from pdagent.core.ids import utc_now
from pdagent.core.rls import verify_rls_context


class OrgSettingsRepo:
    """Data access layer for `org_settings` and per-org token/cost usage rollups."""

    @staticmethod
    async def get_or_create(session: AsyncSession, *, org_id: UUID) -> OrgSettingsRow:
        await verify_rls_context(session)
        stmt = select(OrgSettingsRow).where(OrgSettingsRow.org_id == org_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing
        row = OrgSettingsRow(org_id=org_id, updated_at=utc_now())
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def update_settings(
        session: AsyncSession,
        *,
        org_id: UUID,
        agent_enabled: bool | None = None,
        tone: str | None = None,
        enabled_tools: list[str] | None = None,
        handoff_timeout_seconds: int | None = None,
        daily_budget_usd: float | None = None,
        user_daily_budget_usd: float | None = None,
        retention_days: int | None = None,
        emergency_phone: str | None = None,
        prompt_version: str | None = None,
    ) -> OrgSettingsRow:
        row = await OrgSettingsRepo.get_or_create(session, org_id=org_id)
        if agent_enabled is not None:
            row.agent_enabled = agent_enabled
        if tone is not None:
            row.tone = tone
        if enabled_tools is not None:
            row.enabled_tools = list(enabled_tools)
        if handoff_timeout_seconds is not None:
            row.handoff_timeout_seconds = handoff_timeout_seconds
        if daily_budget_usd is not None:
            row.daily_budget_usd = daily_budget_usd
        if user_daily_budget_usd is not None:
            row.user_daily_budget_usd = user_daily_budget_usd
        if retention_days is not None:
            row.retention_days = retention_days
        if emergency_phone is not None:
            row.emergency_phone = emergency_phone
        if prompt_version is not None:
            row.prompt_version = prompt_version
        row.updated_at = utc_now()
        await session.flush()
        return row

    @staticmethod
    async def compute_org_usage(session: AsyncSession, *, org_id: UUID) -> dict[str, object]:
        """Compute token, cost, cache-read, and escalation aggregates for `org_id`."""
        await verify_rls_context(session)
        msg_stmt = select(
            func.count(MessageRow.id),
            func.coalesce(func.sum(MessageRow.input_tokens), 0),
            func.coalesce(func.sum(MessageRow.output_tokens), 0),
            func.coalesce(func.sum(MessageRow.cache_read_tokens), 0),
            func.coalesce(func.sum(MessageRow.reasoning_tokens), 0),
            func.coalesce(func.sum(MessageRow.cost_usd), 0.0),
        ).where(
            MessageRow.org_id == org_id,
            MessageRow.sender_role == "assistant",
        )
        msg_row = (await session.execute(msg_stmt)).one()

        conv_total = (
            await session.execute(
                select(func.count(ConversationRow.id)).where(ConversationRow.org_id == org_id)
            )
        ).scalar_one()
        conv_escalated = (
            await session.execute(
                select(func.count(ConversationRow.id)).where(
                    ConversationRow.org_id == org_id,
                    ConversationRow.status.in_(("waiting", "staff")),
                )
            )
        ).scalar_one()

        turns = int(msg_row[0] or 0)
        total_cost = round(float(msg_row[5] or 0.0), 6)
        resolved = max(0, int(conv_total) - int(conv_escalated))
        cost_per_resolved = round(total_cost / resolved, 6) if resolved > 0 else 0.0
        escalation_rate = (
            round(int(conv_escalated) / int(conv_total), 4) if int(conv_total) > 0 else 0.0
        )
        org_hash = hashlib.sha256(str(org_id).encode("utf-8")).hexdigest()[:16]

        return {
            "org_id": str(org_id),
            "org_hash": org_hash,
            "assistant_turns": turns,
            "input_tokens": int(msg_row[1] or 0),
            "output_tokens": int(msg_row[2] or 0),
            "cache_read_tokens": int(msg_row[3] or 0),
            "reasoning_tokens": int(msg_row[4] or 0),
            "total_cost_usd": total_cost,
            "conversations_total": int(conv_total),
            "conversations_escalated": int(conv_escalated),
            "escalation_rate": escalation_rate,
            "cost_per_resolved_conversation_usd": cost_per_resolved,
        }
