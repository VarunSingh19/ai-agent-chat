"""Append-only audit logging service (Phase 1, Rules.md §1 Rule 7)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.audit.models import AuditLogRow
from pdagent.auth.principal import Principal
from pdagent.core.ids import new_id, utc_now
from pdagent.core.logging import FORBIDDEN_LOG_KEYS, sanitize_log_text
from pdagent.core.rls import verify_rls_context


def _sanitize_audit_metadata(meta: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for k, v in meta.items():
        if k.lower() in FORBIDDEN_LOG_KEYS:
            cleaned[k] = "[REDACTED_PII]"
        elif isinstance(v, str):
            cleaned[k] = sanitize_log_text(v)
        elif isinstance(v, (int, float, bool)) or v is None:
            cleaned[k] = v
        else:
            cleaned[k] = sanitize_log_text(str(v))
    return cleaned


class AuditService:
    """Service for recording and querying tenant-scoped append-only audit events."""

    @staticmethod
    async def record(
        session: AsyncSession,
        *,
        principal: Principal,
        action: str,
        target_type: str,
        target_id: str,
        outcome: str,
        metadata: dict[str, object] | None = None,
    ) -> AuditLogRow:
        """Insert a sanitized, append-only row into `audit_log` inside an RLS transaction."""
        rls_org = await verify_rls_context(session)
        if rls_org != principal.org_id:
            msg = "RLS context org_id does not match Principal.org_id"
            raise RuntimeError(msg)

        row = AuditLogRow(
            id=new_id(),
            org_id=principal.org_id,
            actor_user_id=principal.user_id,
            actor_role=principal.role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            metadata_json=_sanitize_audit_metadata(metadata or {}),
            created_at=utc_now(),
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def list_for_org(
        session: AsyncSession,
        *,
        org_id: UUID,
        limit: int = 50,
    ) -> list[AuditLogRow]:
        """List recent audit log entries for the active tenant org."""
        await verify_rls_context(session)
        stmt = (
            select(AuditLogRow)
            .where(AuditLogRow.org_id == org_id)
            .order_by(AuditLogRow.created_at.desc())
            .limit(min(limit, 100))
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())
