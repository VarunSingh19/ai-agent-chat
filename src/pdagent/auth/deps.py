"""FastAPI authentication, authorization, and RLS session dependencies (Phase 1)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.auth.principal import Principal, Role
from pdagent.auth.token import TokenVerifier
from pdagent.core.errors import AppError, ErrorCode
from pdagent.core.rls import tenant_transaction


async def get_principal(request: Request) -> Principal:
    """Verify the Bearer JWT from the Authorization header and return the Principal."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise AppError(
            code=ErrorCode.AUTH_INVALID_TOKEN,
            title="Authentication Required",
            detail="Authorization header must use Bearer scheme.",
            status_code=401,
        )
    raw_token = auth_header.removeprefix("Bearer ").strip()
    verifier: TokenVerifier = getattr(request.app.state, "token_verifier", TokenVerifier())
    redis_client = getattr(request.app.state, "redis_client", None)
    principal = await verifier.verify_token(raw_token, redis_client=redis_client)
    request.state.principal = principal
    return principal


def require_roles(
    *allowed_roles: Role,
) -> Callable[[Principal], Coroutine[Any, Any, Principal]]:
    """Dependency factory enforcing that the caller's role is in `allowed_roles`."""

    async def _check_role(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in allowed_roles:
            raise AppError(
                code=ErrorCode.AUTH_FORBIDDEN,
                title="Forbidden",
                detail="Your role is not permitted to perform this action.",
                status_code=403,
            )
        return principal

    return _check_role


async def get_tenant_session(
    request: Request,
    principal: Principal = Depends(get_principal),
) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession inside a transaction with `app.org_id` set to `principal.org_id`."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session, tenant_transaction(session, principal.org_id):
        yield session
