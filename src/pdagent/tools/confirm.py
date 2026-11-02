"""Write-tool confirmation lifecycle and atomic single-UPDATE consumption (Phase 5, Rules.md §1
Rule 3).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy import DateTime, String, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pdagent.audit.service import AuditService
from pdagent.auth.deps import get_principal, get_tenant_session
from pdagent.auth.principal import Principal
from pdagent.core.db import Base
from pdagent.core.errors import AppError, ErrorCode
from pdagent.core.ids import new_id, utc_now
from pdagent.core.rls import verify_rls_context
from pdagent.mcp_server.pdapi_client import PropertyDekApiClient
from pdagent.mcp_server.tools_write import execute_confirmed_write_tool
from pdagent.tools.schemas import canonical_json_hash

router = APIRouter(prefix="/v1/confirmations", tags=["confirmations"])


class ConfirmationRow(Base):
    """Pending or consumed write-tool confirmation (`confirmations` table with RLS)."""

    __tablename__ = "confirmations"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    args_json: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_json: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ConfirmActionRequest(BaseModel):
    """Optional client-echoed arguments or hash to verify argument integrity on confirm."""

    arguments: dict[str, object] | None = None
    args_hash: str | None = None


class ConfirmationService:
    """Manages creation, void-on-edit, cancellation, and atomic consumption of confirmations."""

    @staticmethod
    async def create_pending_card(
        session: AsyncSession,
        *,
        principal: Principal,
        conversation_id: UUID,
        tool_name: str,
        arguments: dict[str, object],
        ttl_minutes: int = 10,
    ) -> dict[str, object]:
        """Void any prior pending confirmation on the thread and create a new 10-min card."""
        await verify_rls_context(session)
        await session.execute(
            update(ConfirmationRow)
            .where(
                ConfirmationRow.org_id == principal.org_id,
                ConfirmationRow.user_id == principal.user_id,
                ConfirmationRow.conversation_id == conversation_id,
                ConfirmationRow.status == "pending",
            )
            .values(status="voided")
        )

        now = utc_now()
        expires = now + timedelta(minutes=ttl_minutes)
        computed_hash = canonical_json_hash(arguments)
        summary_text = _build_summary(tool_name, arguments)

        row = ConfirmationRow(
            id=new_id(),
            org_id=principal.org_id,
            user_id=principal.user_id,
            conversation_id=conversation_id,
            tool_name=tool_name,
            args_json=arguments,
            args_hash=computed_hash,
            summary=summary_text,
            status="pending",
            expires_at=expires,
            created_at=now,
        )
        session.add(row)
        await session.flush()

        await AuditService.record(
            session,
            principal=principal,
            action="confirmation.created",
            target_type="confirmation",
            target_id=str(row.id),
            outcome="pending",
            metadata={"tool_name": tool_name, "args_hash": computed_hash},
        )

        return {
            "id": str(row.id),
            "tool": tool_name,
            "summary": summary_text,
            "args_hash": computed_hash,
            "expires_at": expires.isoformat(),
        }

    @staticmethod
    async def confirm_and_execute(
        session: AsyncSession,
        *,
        principal: Principal,
        confirmation_id: UUID,
        idempotency_key: str,
        pdapi: PropertyDekApiClient,
        expected_arguments: dict[str, object] | None = None,
        expected_args_hash: str | None = None,
    ) -> dict[str, object]:
        """Consume a pending confirmation via one atomic UPDATE ... RETURNING and execute the
        write.
        """
        await verify_rls_context(session)
        existing_stmt = select(ConfirmationRow).where(
            ConfirmationRow.id == confirmation_id,
            ConfirmationRow.org_id == principal.org_id,
        )
        existing = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing is None or existing.user_id != principal.user_id:
            # Rules.md §3: Object missing or in another org/user's scope -> 404, never 403
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Confirmation Not Found",
                detail="The requested confirmation was not found.",
                status_code=404,
            )

        # Idempotent retry with the exact same Idempotency-Key returns the already-saved result
        if (
            existing.status == "confirmed"
            and existing.idempotency_key == idempotency_key
            and existing.result_json is not None
        ):
            return {
                "confirmation_id": str(existing.id),
                "status": "confirmed",
                "tool": existing.tool_name,
                "result": existing.result_json,
                "idempotent_replay": True,
            }

        hash_to_match = existing.args_hash
        if expected_arguments is not None:
            hash_to_match = canonical_json_hash(expected_arguments)
        elif expected_args_hash is not None:
            hash_to_match = expected_args_hash

        # Rules.md §1 Rule 3: Single atomic UPDATE ... WHERE status='pending' RETURNING
        atomic_sql = text(
            """
            UPDATE confirmations
            SET status = 'confirmed',
                confirmed_at = :now_utc,
                idempotency_key = :idem_key
            WHERE id = :conf_id
              AND org_id = :org_id
              AND user_id = :user_id
              AND status = 'pending'
              AND expires_at > :now_utc
              AND args_hash = :expected_hash
            RETURNING id, tool_name, args_json
            """
        )
        now_utc = utc_now()
        res = await session.execute(
            atomic_sql,
            {
                "now_utc": now_utc,
                "idem_key": idempotency_key,
                "conf_id": confirmation_id,
                "org_id": principal.org_id,
                "user_id": principal.user_id,
                "expected_hash": hash_to_match,
            },
        )
        consumed_row = res.first()
        if consumed_row is None:
            await AuditService.record(
                session,
                principal=principal,
                action="confirmation.rejected",
                target_type="confirmation",
                target_id=str(confirmation_id),
                outcome="rejected",
                metadata={"status_before": existing.status},
            )
            raise AppError(
                code=ErrorCode.CONFIRMATION_EXPIRED,
                title="Confirmation Expired or Invalid",
                detail="This confirmation has expired, was already used, or its arguments changed.",
                status_code=410,
            )

        tool_name = str(consumed_row[1])
        raw_args: dict[str, Any] = (
            dict(consumed_row[2]) if isinstance(consumed_row[2], dict) else {}
        )

        try:
            tool_result = await execute_confirmed_write_tool(
                tool_name,
                raw_args,
                principal=principal,
                pdapi=pdapi,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:
            # Rules.md §3: PropertyDek 5xx/timeout to a write tool keeps confirmation pending until
            # expiry
            await session.execute(
                update(ConfirmationRow)
                .where(ConfirmationRow.id == confirmation_id)
                .values(status="pending", confirmed_at=None, idempotency_key=None)
            )
            raise AppError(
                code=ErrorCode.PROVIDER_UNAVAILABLE,
                title="Write Execution Failed",
                detail=(
                    "PropertyDek could not complete the request; your confirmation remains pending."
                ),
                status_code=503,
            ) from exc

        await session.execute(
            update(ConfirmationRow)
            .where(ConfirmationRow.id == confirmation_id)
            .values(result_json=tool_result)
        )
        await AuditService.record(
            session,
            principal=principal,
            action="confirmation.executed",
            target_type="confirmation",
            target_id=str(confirmation_id),
            outcome="confirmed",
            metadata={"tool_name": tool_name},
        )
        return {
            "confirmation_id": str(confirmation_id),
            "status": "confirmed",
            "tool": tool_name,
            "result": tool_result,
            "idempotent_replay": False,
        }

    @staticmethod
    async def cancel_confirmation(
        session: AsyncSession,
        *,
        principal: Principal,
        confirmation_id: UUID,
    ) -> dict[str, object]:
        await verify_rls_context(session)
        existing = (
            await session.execute(
                select(ConfirmationRow).where(
                    ConfirmationRow.id == confirmation_id,
                    ConfirmationRow.org_id == principal.org_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None or existing.user_id != principal.user_id:
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Confirmation Not Found",
                detail="The requested confirmation was not found.",
                status_code=404,
            )

        await session.execute(
            update(ConfirmationRow)
            .where(
                ConfirmationRow.id == confirmation_id,
                ConfirmationRow.org_id == principal.org_id,
                ConfirmationRow.user_id == principal.user_id,
                ConfirmationRow.status == "pending",
            )
            .values(status="cancelled")
        )
        await AuditService.record(
            session,
            principal=principal,
            action="confirmation.cancelled",
            target_type="confirmation",
            target_id=str(confirmation_id),
            outcome="cancelled",
        )
        return {"confirmation_id": str(confirmation_id), "status": "cancelled"}


def _build_summary(tool_name: str, arguments: dict[str, object]) -> str:
    if tool_name == "create_request":
        cat = arguments.get("category", "general")
        urg = arguments.get("urgency", "routine")
        desc = str(arguments.get("description", ""))[:120]
        return f"Create {urg} {cat} work order: {desc}"
    if tool_name == "add_request_note":
        req_id = arguments.get("request_id", "")
        return f"Add note to work order {req_id}"
    if tool_name == "create_task":
        title = str(arguments.get("title", ""))[:120]
        return f"Create staff task: {title}"
    return f"Execute {tool_name}"


@router.post("/{confirmation_id}/confirm")
async def confirm_write_tool(
    confirmation_id: UUID,
    request: Request,
    payload: ConfirmActionRequest | None = None,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Confirm and execute a pending write-tool confirmation card."""
    pdapi: PropertyDekApiClient = request.app.state.pdapi_client
    return await ConfirmationService.confirm_and_execute(
        session,
        principal=principal,
        confirmation_id=confirmation_id,
        idempotency_key=idempotency_key,
        pdapi=pdapi,
        expected_arguments=payload.arguments if payload else None,
        expected_args_hash=payload.args_hash if payload else None,
    )


@router.post("/{confirmation_id}/cancel")
async def cancel_write_tool(
    confirmation_id: UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """Cancel a pending write-tool confirmation card."""
    return await ConfirmationService.cancel_confirmation(
        session,
        principal=principal,
        confirmation_id=confirmation_id,
    )
