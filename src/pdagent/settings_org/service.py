"""Service layer for organisation agent settings and usage reporting (Phase 10)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.audit.models import OrgSettingsRow
from pdagent.audit.service import AuditService
from pdagent.auth.principal import Principal
from pdagent.core.errors import AppError, ErrorCode
from pdagent.settings_org.repo import OrgSettingsRepo
from pdagent.tools.registry import PERMANENTLY_FORBIDDEN_TOOLS


class OrgSettingsService:
    """Enforces org_admin permissions and validates enabled tools
    against the hard exclusion list."""

    @staticmethod
    async def get_settings(session: AsyncSession, *, principal: Principal) -> OrgSettingsRow:
        return await OrgSettingsRepo.get_or_create(session, org_id=principal.org_id)

    @staticmethod
    async def update_settings(
        session: AsyncSession,
        *,
        principal: Principal,
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
        if enabled_tools is not None:
            for t_name in enabled_tools:
                if t_name.strip().lower() in PERMANENTLY_FORBIDDEN_TOOLS:
                    raise AppError(
                        code=ErrorCode.VALIDATION,
                        title="Forbidden Tool Capability",
                        detail=f"Tool '{t_name}' is permanently excluded by Rules.md §1 Rule 4.",
                        status_code=422,
                    )

        row = await OrgSettingsRepo.update_settings(
            session,
            org_id=principal.org_id,
            agent_enabled=agent_enabled,
            tone=tone,
            enabled_tools=enabled_tools,
            handoff_timeout_seconds=handoff_timeout_seconds,
            daily_budget_usd=daily_budget_usd,
            user_daily_budget_usd=user_daily_budget_usd,
            retention_days=retention_days,
            emergency_phone=emergency_phone,
            prompt_version=prompt_version,
        )
        await AuditService.record(
            session,
            principal=principal,
            action="settings.updated",
            target_type="org_settings",
            target_id=str(principal.org_id),
            outcome="updated",
            metadata={
                "daily_budget_usd": row.daily_budget_usd,
                "enabled_tools_count": len(row.enabled_tools),
            },
        )
        return row

    @staticmethod
    async def get_usage(session: AsyncSession, *, principal: Principal) -> dict[str, object]:
        """Return org usage. `fbc_operator` receives hashed org aggregates only (Decision D-021)."""
        usage = await OrgSettingsRepo.compute_org_usage(session, org_id=principal.org_id)
        if principal.role == "fbc_operator":
            redacted = dict(usage)
            redacted.pop("org_id", None)
            return redacted
        return usage
