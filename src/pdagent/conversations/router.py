"""FastAPI router for `/v1/conversations` (Architecture.md §8, Phase 2)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.auth.deps import get_tenant_session, require_roles
from pdagent.auth.principal import Principal
from pdagent.conversations.schemas import (
    ConversationOut,
    CreateConversationRequest,
    MessageOut,
    SendMessageRequest,
)
from pdagent.conversations.service import ConversationService
from pdagent.conversations.stream import render_sse_stream

router = APIRouter(prefix="/v1/conversations", tags=["conversations"])


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def open_or_resume_conversation(
    payload: CreateConversationRequest | None = None,
    principal: Principal = Depends(require_roles("tenant", "pm_member", "org_admin")),
    session: AsyncSession = Depends(get_tenant_session),
) -> ConversationOut:
    """Open or resume the signed-in user's conversation thread."""
    channel = payload.channel if payload else "web"
    prop_id = payload.property_id if payload else None
    conv = await ConversationService.open_or_resume(
        session, principal=principal, channel=channel, property_id=prop_id
    )
    return ConversationOut(
        id=str(conv.id),
        channel=conv.channel,
        status=conv.status,
        property_id=str(conv.property_id) if conv.property_id else None,
        assigned_to=str(conv.assigned_to) if conv.assigned_to else None,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
    )


@router.get("/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: UUID,
    after_seq: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_roles("tenant", "pm_member", "org_admin")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Fetch or resume conversation messages after `after_seq`."""
    rows = await ConversationService.list_history(
        session,
        principal=principal,
        conversation_id=conversation_id,
        after_seq=after_seq,
    )
    items = [
        MessageOut(
            id=str(r.id),
            seq=r.seq,
            sender_role=r.sender_role,
            content=r.content,
            model=r.model,
            provider=r.provider,
            route=r.route,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            cache_read_tokens=r.cache_read_tokens,
            reasoning_tokens=r.reasoning_tokens,
            cost_usd=r.cost_usd,
            latency_ms=r.latency_ms,
            failover=r.failover,
            degraded=r.degraded,
            sources=list(r.sources_json),
            created_at=r.created_at.isoformat(),
        ).model_dump()
        for r in rows
    ]
    return {"items": items, "next_cursor": None}


@router.post("/{conversation_id}/messages")
async def send_conversation_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    principal: Principal = Depends(require_roles("tenant", "pm_member", "org_admin")),
    session: AsyncSession = Depends(get_tenant_session),
) -> StreamingResponse:
    """Send a user message and stream the assistant response via Server-Sent Events (SSE)."""
    events = await ConversationService.handle_user_turn(
        session,
        principal=principal,
        conversation_id=conversation_id,
        user_content=payload.content,
        idempotency_key=idempotency_key,
        gateway=request.app.state.provider_gateway,
        rate_limiter=request.app.state.rate_limiter,
        spend_guard=request.app.state.spend_guard,
        pdapi=request.app.state.pdapi_client,
        notifier=request.app.state.staff_notifier,
        embedder=getattr(request.app.state, "embedder", None),
        unhelpful_previous=payload.unhelpful_previous,
    )
    return StreamingResponse(
        render_sse_stream(events),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store"},
    )
