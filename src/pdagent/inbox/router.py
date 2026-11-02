"""FastAPI router for `/v1/inbox` staff endpoints (Architecture.md §8, Phase 6)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.auth.deps import get_tenant_session, require_roles
from pdagent.auth.principal import Principal
from pdagent.inbox.service import InboxService

router = APIRouter(prefix="/v1/inbox", tags=["inbox"])


class StaffMessagePayload(BaseModel):
    """Body for `POST /v1/inbox/conversations/{id}/messages`."""

    content: str = Field(min_length=1, max_length=4000)


@router.get("/conversations")
async def list_inbox_conversations(
    status: str | None = Query(default=None),
    principal: Principal = Depends(require_roles("pm_member", "org_admin")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """List conversations visible to the staff member's assigned properties."""
    rows = await InboxService.list_threads(session, principal=principal, status_filter=status)
    items = [
        {
            "id": str(r.id),
            "user_id": str(r.user_id),
            "property_id": str(r.property_id) if r.property_id else None,
            "channel": r.channel,
            "status": r.status,
            "assigned_to": str(r.assigned_to) if r.assigned_to else None,
            "rolling_summary": r.rolling_summary,
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]
    return {"items": items, "next_cursor": None}


@router.get("/conversations/{conversation_id}")
async def get_inbox_conversation_transcript(
    conversation_id: UUID,
    principal: Principal = Depends(require_roles("pm_member", "org_admin")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Return full conversation details and transcript for an authorized staff member."""
    conv, msgs = await InboxService.get_thread_transcript(
        session, principal=principal, conversation_id=conversation_id
    )
    return {
        "id": str(conv.id),
        "user_id": str(conv.user_id),
        "property_id": str(conv.property_id) if conv.property_id else None,
        "status": conv.status,
        "assigned_to": str(conv.assigned_to) if conv.assigned_to else None,
        "rolling_summary": conv.rolling_summary,
        "messages": [
            {
                "id": str(m.id),
                "seq": m.seq,
                "sender_role": m.sender_role,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in msgs
        ],
    }


@router.post("/conversations/{conversation_id}/take")
async def take_inbox_conversation(
    conversation_id: UUID,
    principal: Principal = Depends(require_roles("pm_member", "org_admin")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Atomically claim a `waiting` conversation (`409 CONFLICT_TAKEN` if already taken)."""
    conv = await InboxService.take_thread(
        session, principal=principal, conversation_id=conversation_id
    )
    return {
        "id": str(conv.id),
        "status": conv.status,
        "assigned_to": str(conv.assigned_to) if conv.assigned_to else None,
    }


@router.post("/conversations/{conversation_id}/release")
async def release_inbox_conversation(
    conversation_id: UUID,
    principal: Principal = Depends(require_roles("pm_member", "org_admin")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Release a staff-owned conversation back to `ai`."""
    conv = await InboxService.release_thread(
        session, principal=principal, conversation_id=conversation_id
    )
    return {"id": str(conv.id), "status": conv.status, "assigned_to": None}


@router.post("/conversations/{conversation_id}/messages")
async def post_staff_reply(
    conversation_id: UUID,
    payload: StaffMessagePayload,
    principal: Principal = Depends(require_roles("pm_member", "org_admin")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Send a staff reply into a conversation thread."""
    msg = await InboxService.send_staff_reply(
        session,
        principal=principal,
        conversation_id=conversation_id,
        content=payload.content,
    )
    return {
        "id": str(msg.id),
        "seq": msg.seq,
        "sender_role": msg.sender_role,
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
    }
