"""FastAPI router for `POST /v1/conversations/{id}/handoff` (Architecture.md §8, Phase 6)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.auth.deps import get_principal, get_tenant_session
from pdagent.auth.principal import Principal
from pdagent.handoff.notify import StaffAlertDispatcher
from pdagent.handoff.service import HandoffService

router = APIRouter(prefix="/v1/conversations", tags=["handoff"])


class HandoffRequestPayload(BaseModel):
    """Optional user reason when requesting a human representative."""

    reason: str = Field(default="user_requested_human", max_length=64)


@router.post("/{conversation_id}/handoff")
async def request_human_handoff(
    conversation_id: UUID,
    request: Request,
    payload: HandoffRequestPayload | None = None,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Escalate a conversation to `waiting` for property management staff."""
    notifier: StaffAlertDispatcher = request.app.state.staff_notifier
    reason = payload.reason if payload else "user_requested_human"
    handoff = await HandoffService.escalate_conversation(
        session,
        principal=principal,
        conversation_id=conversation_id,
        reason=reason,
        is_emergency=False,
        notifier=notifier,
    )
    return {
        "handoff_id": str(handoff.id),
        "conversation_id": str(conversation_id),
        "state": handoff.state,
        "timeout_at": handoff.timeout_at.isoformat(),
    }
