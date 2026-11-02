"""Row-Level Security (RLS) transaction context enforcement (Rules.md §1 Rule 2)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_tenant_rls_context(session: AsyncSession, org_id: UUID) -> None:
    """Set `app.org_id` for the current database transaction (`SET LOCAL`)."""
    await session.execute(
        text("SELECT set_config('app.org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )


async def verify_rls_context(session: AsyncSession) -> UUID:
    """Verify `app.org_id` is set in the active transaction; raise RuntimeError if missing."""
    result = await session.execute(text("SELECT current_setting('app.org_id', true)"))
    raw = result.scalar()
    if not raw or not str(raw).strip():
        msg = (
            "Tenant query attempted outside a transaction with app.org_id set (Rules.md §1 Rule 2)"
        )
        raise RuntimeError(msg)
    return UUID(str(raw).strip())


@asynccontextmanager
async def tenant_transaction(session: AsyncSession, org_id: UUID) -> AsyncIterator[AsyncSession]:
    """Open a transaction (or nested transaction) and bind `app.org_id` for RLS policies."""
    if session.in_transaction():
        await set_tenant_rls_context(session, org_id)
        yield session
    else:
        async with session.begin():
            await set_tenant_rls_context(session, org_id)
            yield session
