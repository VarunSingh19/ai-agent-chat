"""SQLAlchemy models and repository for `conversations` and `messages` (Phase 2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pdagent.core.db import Base
from pdagent.core.ids import new_id, utc_now
from pdagent.core.rls import verify_rls_context


class ConversationRow(Base):
    """Tenant conversation thread (`conversations` table with RLS)."""

    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    property_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    unit_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="web")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")
    assigned_to: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    rolling_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unhelpful_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class MessageRow(Base):
    """Monotonically sequenced message inside a conversation (`messages` table with RLS)."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    sender_role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sources_json: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ConversationRepo:
    """Repository for `conversations` and `messages` enforcing RLS and monotonic `seq`."""

    @staticmethod
    async def create_or_resume(
        session: AsyncSession,
        *,
        org_id: UUID,
        user_id: UUID,
        channel: str,
        property_id: UUID | None,
        unit_id: UUID | None,
    ) -> ConversationRow:
        await verify_rls_context(session)
        stmt = (
            select(ConversationRow)
            .where(
                ConversationRow.org_id == org_id,
                ConversationRow.user_id == user_id,
                ConversationRow.channel == channel,
                ConversationRow.status != "closed",
            )
            .order_by(ConversationRow.updated_at.desc())
            .limit(1)
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

        now = utc_now()
        row = ConversationRow(
            id=new_id(),
            org_id=org_id,
            user_id=user_id,
            property_id=property_id,
            unit_id=unit_id,
            channel=channel,
            status="ai",
            rolling_summary="",
            unhelpful_count=0,
            next_seq=1,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def get_for_principal(
        session: AsyncSession,
        *,
        org_id: UUID,
        conversation_id: UUID,
    ) -> ConversationRow | None:
        await verify_rls_context(session)
        stmt = select(ConversationRow).where(
            ConversationRow.org_id == org_id,
            ConversationRow.id == conversation_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def find_by_idempotency_key(
        session: AsyncSession,
        *,
        org_id: UUID,
        conversation_id: UUID,
        idempotency_key: str,
    ) -> MessageRow | None:
        await verify_rls_context(session)
        stmt = select(MessageRow).where(
            MessageRow.org_id == org_id,
            MessageRow.conversation_id == conversation_id,
            MessageRow.idempotency_key == idempotency_key,
            MessageRow.sender_role == "assistant",
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def append_message(
        session: AsyncSession,
        *,
        org_id: UUID,
        conversation_id: UUID,
        sender_role: str,
        content: str,
        model: str | None = None,
        provider: str | None = None,
        route: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        reasoning_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        failover: bool = False,
        degraded: bool = False,
        sources: list[dict[str, object]] | None = None,
        idempotency_key: str | None = None,
    ) -> MessageRow:
        """Atomically allocate the next `seq` on `conversations` and insert a `MessageRow`."""
        await verify_rls_context(session)
        seq_res = await session.execute(
            text(
                """
                UPDATE conversations
                SET next_seq = next_seq + 1,
                    updated_at = :now_utc
                WHERE id = :conv_id AND org_id = :org_id
                RETURNING next_seq - 1
                """
            ),
            {"now_utc": utc_now(), "conv_id": conversation_id, "org_id": org_id},
        )
        seq_row = seq_res.first()
        if seq_row is None:
            msg = f"Conversation {conversation_id} not found when allocating seq"
            raise RuntimeError(msg)
        allocated_seq = int(seq_row[0])

        msg_row = MessageRow(
            id=new_id(),
            org_id=org_id,
            conversation_id=conversation_id,
            seq=allocated_seq,
            sender_role=sender_role,
            content=content,
            model=model,
            provider=provider,
            route=route,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            reasoning_tokens=reasoning_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            failover=failover,
            degraded=degraded,
            sources_json=sources or [],
            idempotency_key=idempotency_key,
            created_at=utc_now(),
        )
        session.add(msg_row)
        await session.flush()
        return msg_row

    @staticmethod
    async def list_messages(
        session: AsyncSession,
        *,
        org_id: UUID,
        conversation_id: UUID,
        after_seq: int = 0,
        limit: int = 100,
    ) -> list[MessageRow]:
        await verify_rls_context(session)
        stmt = (
            select(MessageRow)
            .where(
                MessageRow.org_id == org_id,
                MessageRow.conversation_id == conversation_id,
                MessageRow.seq > after_seq,
            )
            .order_by(MessageRow.seq.asc())
            .limit(min(limit, 100))
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def update_rolling_summary_and_unhelpful(
        session: AsyncSession,
        *,
        org_id: UUID,
        conversation_id: UUID,
        rolling_summary: str,
        unhelpful_count: int,
    ) -> None:
        await verify_rls_context(session)
        await session.execute(
            update(ConversationRow)
            .where(
                ConversationRow.org_id == org_id,
                ConversationRow.id == conversation_id,
            )
            .values(
                rolling_summary=rolling_summary,
                unhelpful_count=unhelpful_count,
                updated_at=utc_now(),
            )
        )
