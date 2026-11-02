"""Handoff state machine and SQLAlchemy model (`handoffs` table with RLS, Architecture.md §7d)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from pdagent.core.db import Base
from pdagent.core.ids import new_id, utc_now

ConversationStatus = Literal["ai", "waiting", "staff", "closed"]

VALID_TRANSITIONS: dict[ConversationStatus, frozenset[ConversationStatus]] = {
    "ai": frozenset({"waiting", "closed"}),
    "waiting": frozenset({"staff", "ai", "closed"}),
    "staff": frozenset({"ai", "closed"}),
    "closed": frozenset({"ai", "waiting"}),
}


def can_transition(current: ConversationStatus, target: ConversationStatus) -> bool:
    """Return True if transitioning from `current` to `target` is valid per Architecture.md §7d."""
    return target in VALID_TRANSITIONS.get(current, frozenset())


class HandoffRow(Base):
    """Handoff escalation record (`handoffs` table with RLS)."""

    __tablename__ = "handoffs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    is_emergency: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    matched_rule: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="waiting")
    assigned_to: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    timeout_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
