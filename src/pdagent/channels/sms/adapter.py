"""SMS provider adapter, HMAC signature verification, and STOP/START persistence (Phase 8)."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pdagent.auth.principal import Principal
from pdagent.channels.sms.parse import hash_phone_number, parse_sms_compliance_command
from pdagent.conversations.repo import ConversationRepo
from pdagent.core.db import Base
from pdagent.core.errors import AppError, ErrorCode
from pdagent.core.ids import new_id, utc_now
from pdagent.core.rls import verify_rls_context
from pdagent.handoff.emergency import check_emergency_message


class SmsOptOutRow(Base):
    """Per-organisation SMS STOP/START opt-out state (`sms_opt_outs` table with RLS)."""

    __tablename__ = "sms_opt_outs"
    __table_args__ = (UniqueConstraint("org_id", "phone_hash", name="uq_sms_opt_outs_org_phone"),)

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


@dataclass(frozen=True, slots=True)
class SmsReplyOutcome:
    """Result of processing an inbound SMS webhook."""

    status: str
    outbound_sent: bool
    reply_text: str | None
    replayed: bool = False
    anonymous_mode: bool = False


class SmsChannelAdapter:
    """Handles signature verification, replay protection, phone resolution, and STOP/START."""

    def __init__(self, webhook_secret: str) -> None:
        self._secret = webhook_secret
        self._seen_message_sids: set[str] = set()
        self._phone_directory: dict[tuple[UUID, str], Principal] = {}
        self.delivery_statuses: dict[str, str] = {}

    def register_tenant_phone(self, org_id: UUID, raw_phone: str, principal: Principal) -> None:
        """Register a verified tenant phone mapping for `(org_id, phone_hash)`."""
        p_hash = hash_phone_number(raw_phone)
        self._phone_directory[(org_id, p_hash)] = principal

    def compute_signature(self, message_sid: str, from_phone: str, body: str) -> str:
        """Compute HMAC-SHA256 webhook signature over `message_sid|from_phone|body`."""
        payload = f"{message_sid}|{from_phone}|{body}".encode()
        return hmac.new(self._secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()

    def verify_signature(
        self, *, signature: str, message_sid: str, from_phone: str, body: str
    ) -> None:
        expected = self.compute_signature(message_sid, from_phone, body)
        if not hmac.compare_digest(signature.strip(), expected):
            raise AppError(
                code=ErrorCode.AUTH_INVALID_TOKEN,
                title="Invalid Webhook Signature",
                detail="SMS webhook signature verification failed.",
                status_code=401,
            )

    async def handle_inbound(
        self,
        session: AsyncSession,
        *,
        org_id: UUID,
        message_sid: str,
        from_phone: str,
        body: str,
    ) -> SmsReplyOutcome:
        """Process inbound SMS with replay deduplication, STOP/START compliance, and anonymous
        safety.
        """
        await verify_rls_context(session)
        if message_sid in self._seen_message_sids:
            return SmsReplyOutcome(
                status="duplicate_ignored",
                outbound_sent=False,
                reply_text=None,
                replayed=True,
            )
        self._seen_message_sids.add(message_sid)

        phone_hash = hash_phone_number(from_phone)
        cmd = parse_sms_compliance_command(body)

        stmt = select(SmsOptOutRow).where(
            SmsOptOutRow.org_id == org_id,
            SmsOptOutRow.phone_hash == phone_hash,
        )
        opt_row = (await session.execute(stmt)).scalar_one_or_none()

        if cmd == "opt_out":
            if opt_row is None:
                opt_row = SmsOptOutRow(
                    id=new_id(),
                    org_id=org_id,
                    phone_hash=phone_hash,
                    opted_out=True,
                    updated_at=utc_now(),
                )
                session.add(opt_row)
            else:
                opt_row.opted_out = True
                opt_row.updated_at = utc_now()
            await session.flush()
            return SmsReplyOutcome(
                status="opted_out",
                outbound_sent=False,
                reply_text=None,
            )

        if cmd == "opt_in":
            if opt_row is not None:
                opt_row.opted_out = False
                opt_row.updated_at = utc_now()
                await session.flush()
            return SmsReplyOutcome(
                status="opted_in",
                outbound_sent=True,
                reply_text="PropertyDek SMS updates re-enabled. Reply STOP at any time to opt out.",
            )

        # If opted out via a prior STOP, prevent every outbound message until START
        if opt_row is not None and opt_row.opted_out:
            return SmsReplyOutcome(
                status="suppressed_opted_out",
                outbound_sent=False,
                reply_text=None,
            )

        # Pre-LLM emergency check even over SMS
        emg = check_emergency_message(body)
        if emg.matched:
            return SmsReplyOutcome(
                status="emergency_replied",
                outbound_sent=True,
                reply_text=emg.safety_reply,
            )

        principal = self._phone_directory.get((org_id, phone_hash))
        if principal is None:
            # Unknown number: limited anonymous mode (public FAQ & request form link only, never
            # personal data)
            return SmsReplyOutcome(
                status="anonymous_faq",
                outbound_sent=True,
                reply_text=(
                    "PropertyDek Assistant: Because this number is not linked to a verified lease, "
                    "I can only share general community FAQs or our online Maintenance "
                    "Request Form."
                ),
                anonymous_mode=True,
            )

        # Known tenant: keep SMS conversation separate from app/web (`channel="sms"`)
        sms_conv = await ConversationRepo.create_or_resume(
            session,
            org_id=principal.org_id,
            user_id=principal.user_id,
            channel="sms",
            property_id=principal.property_ids[0] if principal.property_ids else None,
            unit_id=principal.unit_id,
        )
        await ConversationRepo.append_message(
            session,
            org_id=principal.org_id,
            conversation_id=sms_conv.id,
            sender_role="user",
            content=body,
        )
        safe_reply = (
            "PropertyDek SMS: We received your message. For security, account details and "
            "work-order confirmations are available in the PropertyDek app."
        )
        await ConversationRepo.append_message(
            session,
            org_id=principal.org_id,
            conversation_id=sms_conv.id,
            sender_role="assistant",
            content=safe_reply,
            route="small",
        )
        return SmsReplyOutcome(
            status="replied",
            outbound_sent=True,
            reply_text=safe_reply,
            anonymous_mode=False,
        )
