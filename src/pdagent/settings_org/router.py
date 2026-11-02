"""FastAPI router for `/v1/settings/agent` and `/v1/admin/usage` (Architecture.md §8, Phase 10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.auth.deps import get_tenant_session, require_roles
from pdagent.auth.principal import Principal
from pdagent.settings_org.service import OrgSettingsService

router = APIRouter(tags=["settings-org"])


class UpdateOrgSettingsPayload(BaseModel):
    """Payload for `PUT /v1/settings/agent`."""

    agent_enabled: bool | None = None
    tone: str | None = Field(default=None, max_length=32)
    enabled_tools: list[str] | None = None
    handoff_timeout_seconds: int | None = Field(default=None, ge=30, le=3600)
    daily_budget_usd: float | None = Field(default=None, ge=0.0, le=10000.0)
    user_daily_budget_usd: float | None = Field(default=None, ge=0.0, le=1000.0)
    retention_days: int | None = Field(default=None, ge=7, le=365)
    emergency_phone: str | None = Field(default=None, max_length=64)
    prompt_version: str | None = Field(default=None, max_length=32)


@router.get("/v1/settings/agent")
async def get_agent_settings(
    principal: Principal = Depends(require_roles("org_admin", "pm_member")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Fetch current organisation agent configuration."""
    row = await OrgSettingsService.get_settings(session, principal=principal)
    return {
        "org_id": str(row.org_id),
        "agent_enabled": row.agent_enabled,
        "tone": row.tone,
        "enabled_tools": list(row.enabled_tools),
        "handoff_timeout_seconds": row.handoff_timeout_seconds,
        "daily_budget_usd": row.daily_budget_usd,
        "user_daily_budget_usd": row.user_daily_budget_usd,
        "retention_days": row.retention_days,
        "emergency_phone": row.emergency_phone,
        "prompt_version": row.prompt_version,
        "updated_at": row.updated_at.isoformat(),
    }


@router.put("/v1/settings/agent")
async def put_agent_settings(
    payload: UpdateOrgSettingsPayload,
    principal: Principal = Depends(require_roles("org_admin")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Update organisation agent configuration (takes effect on the very next turn)."""
    row = await OrgSettingsService.update_settings(
        session,
        principal=principal,
        agent_enabled=payload.agent_enabled,
        tone=payload.tone,
        enabled_tools=payload.enabled_tools,
        handoff_timeout_seconds=payload.handoff_timeout_seconds,
        daily_budget_usd=payload.daily_budget_usd,
        user_daily_budget_usd=payload.user_daily_budget_usd,
        retention_days=payload.retention_days,
        emergency_phone=payload.emergency_phone,
        prompt_version=payload.prompt_version,
    )
    return {
        "org_id": str(row.org_id),
        "agent_enabled": row.agent_enabled,
        "tone": row.tone,
        "enabled_tools": list(row.enabled_tools),
        "handoff_timeout_seconds": row.handoff_timeout_seconds,
        "daily_budget_usd": row.daily_budget_usd,
        "user_daily_budget_usd": row.user_daily_budget_usd,
        "retention_days": row.retention_days,
        "emergency_phone": row.emergency_phone,
        "prompt_version": row.prompt_version,
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("/v1/admin/usage")
async def get_admin_usage(
    principal: Principal = Depends(require_roles("org_admin", "fbc_operator")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Return cost, tokens, and escalation rate (org_admin: own org; fbc_operator: hashed
    aggregates only).
    """
    return await OrgSettingsService.get_usage(session, principal=principal)
