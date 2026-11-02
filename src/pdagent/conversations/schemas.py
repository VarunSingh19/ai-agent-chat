"""Pydantic schemas for `/v1/conversations` endpoints (Architecture.md §8, Phase 2)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CreateConversationRequest(BaseModel):
    """Request body to open or resume a conversation thread."""

    channel: Literal["web", "app", "sms"] = "web"
    property_id: UUID | None = None


class ConversationOut(BaseModel):
    """Public representation of a conversation."""

    id: str
    channel: str
    status: str
    property_id: str | None = None
    assigned_to: str | None = None
    created_at: str
    updated_at: str


class SendMessageRequest(BaseModel):
    """Request body for `POST /v1/conversations/{id}/messages`."""

    content: str = Field(min_length=1, max_length=4000)
    unhelpful_previous: bool = False


class MessageOut(BaseModel):
    """Public representation of a persisted message."""

    id: str
    seq: int
    sender_role: str
    content: str
    model: str | None = None
    provider: str | None = None
    route: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    failover: bool = False
    degraded: bool = False
    sources: list[dict[str, object]] = Field(default_factory=list)
    created_at: str
