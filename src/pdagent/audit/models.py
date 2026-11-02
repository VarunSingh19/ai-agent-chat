"""SQLAlchemy models for tenant org_settings and append-only audit_log (Phase 1)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pdagent.core.db import Base
from pdagent.core.ids import new_id, utc_now


class OrgSettingsRow(Base):
    """Per-organisation configuration (`org_settings` table with RLS)."""

    __tablename__ = "org_settings"

    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    agent_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tone: Mapped[str] = mapped_column(String(32), nullable=False, default="professional")
    enabled_tools: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: [
            "list_my_requests",
            "get_request",
            "get_balance",
            "list_announcements",
            "get_device_status",
            "search_knowledge",
            "create_request",
            "add_request_note",
        ],
    )
    handoff_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    daily_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=25.0)
    user_daily_budget_usd: Mapped[float] = mapped_column(Float, nullable=False, default=2.50)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    emergency_phone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="1-800-555-0199"
    )
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class AuditLogRow(Base):
    """Append-only security and confirmation audit log (`audit_log` table with RLS)."""

    __tablename__ = "audit_log"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    actor_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
