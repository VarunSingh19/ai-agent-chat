"""Repository for Staff Inbox queries and atomic takeover (Phase 6, Architecture.md §7d)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.conversations.repo import ConversationRow
from pdagent.core.ids import utc_now
from pdagent.core.rls import verify_rls_context
from pdagent.handoff.states import HandoffRow


class InboxRepo:
    """Data access for staff inbox threads and atomic staff takeover (`409 CONFLICT_TAKEN`)."""

    @staticmethod
    async def list_staff_conversations(
        session: AsyncSession,
        *,
        org_id: UUID,
        allowed_property_ids: tuple[UUID, ...],
        is_org_admin: bool,
        status_filter: str | None = None,
        limit: int = 50,
    ) -> list[ConversationRow]:
        await verify_rls_context(session)
        stmt = select(ConversationRow).where(ConversationRow.org_id == org_id)
        if status_filter is not None:
            stmt = stmt.where(ConversationRow.status == status_filter)
        if not is_org_admin:
            if not allowed_property_ids:
                return []
            stmt = stmt.where(ConversationRow.property_id.in_(allowed_property_ids))
        stmt = stmt.order_by(ConversationRow.updated_at.desc()).limit(min(limit, 100))
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def atomic_take(
        session: AsyncSession,
        *,
        org_id: UUID,
        conversation_id: UUID,
        staff_user_id: UUID,
    ) -> bool:
        """Atomically transition a `waiting` conversation to `staff` (Architecture.md §7d).

        Returns True for the single winner and False if another staff member already took it.
        """
        await verify_rls_context(session)
        now = utc_now()
        res = await session.execute(
            text(
                """
                UPDATE conversations
                SET status = 'staff',
                    assigned_to = :staff_id,
                    updated_at = :now_utc
                WHERE id = :conv_id
                  AND org_id = :org_id
                  AND status = 'waiting'
                RETURNING id
                """
            ),
            {
                "staff_id": staff_user_id,
                "now_utc": now,
                "conv_id": conversation_id,
                "org_id": org_id,
            },
        )
        won = res.first() is not None
        if won:
            await session.execute(
                update(HandoffRow)
                .where(
                    HandoffRow.org_id == org_id,
                    HandoffRow.conversation_id == conversation_id,
                    HandoffRow.state == "waiting",
                )
                .values(state="staff", assigned_to=staff_user_id, outcome="staff_taken")
            )
        return won

    @staticmethod
    async def release_to_ai(
        session: AsyncSession,
        *,
        org_id: UUID,
        conversation_id: UUID,
    ) -> None:
        await verify_rls_context(session)
        now = utc_now()
        await session.execute(
            update(ConversationRow)
            .where(
                ConversationRow.org_id == org_id,
                ConversationRow.id == conversation_id,
            )
            .values(status="ai", assigned_to=None, updated_at=now)
        )
        await session.execute(
            update(HandoffRow)
            .where(
                HandoffRow.org_id == org_id,
                HandoffRow.conversation_id == conversation_id,
                HandoffRow.state == "staff",
            )
            .values(state="closed", outcome="released_to_ai")
        )
