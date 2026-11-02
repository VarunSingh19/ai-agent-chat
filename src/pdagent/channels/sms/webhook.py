"""FastAPI router for `/v1/channels/sms/inbound` and `/v1/channels/sms/status` (Phase 8)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from pdagent.channels.sms.adapter import SmsChannelAdapter
from pdagent.core.rls import tenant_transaction

router = APIRouter(prefix="/v1/channels/sms", tags=["sms"])


class SmsInboundPayload(BaseModel):
    """Inbound SMS provider webhook payload."""

    org_id: UUID
    message_sid: str = Field(min_length=1, max_length=128)
    from_phone: str = Field(min_length=5, max_length=32)
    body: str = Field(min_length=1, max_length=1600)


class SmsStatusPayload(BaseModel):
    """Outbound SMS delivery status webhook payload."""

    message_sid: str = Field(min_length=1, max_length=128)
    delivery_status: str = Field(min_length=1, max_length=32)


@router.post("/inbound")
async def sms_inbound_webhook(
    payload: SmsInboundPayload,
    request: Request,
    x_sms_signature: str = Header(..., alias="X-Sms-Signature"),
) -> dict[str, object]:
    """Verify HMAC signature and process inbound SMS under the target org's RLS context."""
    adapter: SmsChannelAdapter = request.app.state.sms_adapter
    adapter.verify_signature(
        signature=x_sms_signature,
        message_sid=payload.message_sid,
        from_phone=payload.from_phone,
        body=payload.body,
    )
    session_factory = request.app.state.session_factory
    async with session_factory() as session, tenant_transaction(session, payload.org_id):
        outcome = await adapter.handle_inbound(
            session,
            org_id=payload.org_id,
            message_sid=payload.message_sid,
            from_phone=payload.from_phone,
            body=payload.body,
        )
        return {
            "status": outcome.status,
            "outbound_sent": outcome.outbound_sent,
            "reply_text": outcome.reply_text,
            "replayed": outcome.replayed,
            "anonymous_mode": outcome.anonymous_mode,
        }


@router.post("/status")
async def sms_delivery_status_webhook(
    payload: SmsStatusPayload,
    request: Request,
    x_sms_signature: str = Header(..., alias="X-Sms-Signature"),
) -> dict[str, object]:
    """Record outbound SMS delivery status after verifying signature."""
    adapter: SmsChannelAdapter = request.app.state.sms_adapter
    adapter.verify_signature(
        signature=x_sms_signature,
        message_sid=payload.message_sid,
        from_phone="status",
        body=payload.delivery_status,
    )
    adapter.delivery_statuses[payload.message_sid] = payload.delivery_status
    return {"message_sid": payload.message_sid, "status": payload.delivery_status}
