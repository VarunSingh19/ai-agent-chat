"""Periodic maintenance tasks: handoff timeout sweeps and retention purge (Architecture.md §3,
§7d).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.conversations.repo import ConversationRow
from pdagent.core.ids import utc_now
from pdagent.core.rls import verify_rls_context
from pdagent.handoff.service import HandoffService
from pdagent.knowledge.repo import DocumentChunkRow, DocumentRow
from pdagent.tools.confirm import ConfirmationRow


async def run_org_periodic_maintenance(
    session: AsyncSession,
    *,
    org_id: UUID,
    retention_days: int = 90,
) -> dict[str, int]:
    """Run handoff timeout sweeps, expired confirmation cleanup,
    and retention purge for `org_id`."""
    await verify_rls_context(session)
    now = utc_now()

    timed_out_handoffs = await HandoffService.process_expired_waiting_handoffs(
        session, org_id=org_id
    )

    # Purge chunks belonging to replaced or deleted documents (Architecture.md §7g)
    replaced_docs_subq = select(DocumentRow.id).where(
        DocumentRow.org_id == org_id,
        DocumentRow.status.in_(("replaced", "deleted")),
    )
    chunk_del = await session.execute(
        delete(DocumentChunkRow).where(
            DocumentChunkRow.org_id == org_id,
            DocumentChunkRow.document_id.in_(replaced_docs_subq),
        )
    )

    # Mark expired pending confirmations as expired
    exp_conf = await session.execute(
        update(ConfirmationRow)
        .where(
            ConfirmationRow.org_id == org_id,
            ConfirmationRow.status == "pending",
            ConfirmationRow.expires_at <= now,
        )
        .values(status="expired")
    )

    # Purge closed conversations older than retention_days
    cutoff = now - timedelta(days=retention_days)
    conv_del = await session.execute(
        delete(ConversationRow).where(
            ConversationRow.org_id == org_id,
            ConversationRow.status == "closed",
            ConversationRow.updated_at < cutoff,
        )
    )

    return {
        "timed_out_handoffs": timed_out_handoffs,
        "purged_chunks": int(getattr(chunk_del, "rowcount", 0) or 0),
        "expired_confirmations": int(getattr(exp_conf, "rowcount", 0) or 0),
        "purged_conversations": int(getattr(conv_del, "rowcount", 0) or 0),
    }
