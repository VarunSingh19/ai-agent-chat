"""Staff Inbox service enforcing property scope and atomic takeover (Phase 6)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.audit.service import AuditService
from pdagent.auth.principal import Principal
from pdagent.conversations.repo import ConversationRepo, ConversationRow, MessageRow
from pdagent.core.errors import AppError, ErrorCode
from pdagent.inbox.repo import InboxRepo


def _staff_can_access(principal: Principal, conv: ConversationRow) -> bool:
    if principal.role == "org_admin":
        return True
    if principal.role == "pm_member":
        if conv.property_id is None:
            return False
        return conv.property_id in principal.property_ids
    return False


class InboxService:
    """Service layer for `/v1/inbox` endpoints."""

    @staticmethod
    async def list_threads(
        session: AsyncSession,
        *,
        principal: Principal,
        status_filter: str | None = None,
    ) -> list[ConversationRow]:
        return await InboxRepo.list_staff_conversations(
            session,
            org_id=principal.org_id,
            allowed_property_ids=principal.property_ids,
            is_org_admin=(principal.role == "org_admin"),
            status_filter=status_filter,
        )

    @staticmethod
    async def get_thread_transcript(
        session: AsyncSession,
        *,
        principal: Principal,
        conversation_id: UUID,
    ) -> tuple[ConversationRow, list[MessageRow]]:
        conv = await ConversationRepo.get_for_principal(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        if conv is None or not _staff_can_access(principal, conv):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Conversation Not Found",
                detail="The requested conversation was not found.",
                status_code=404,
            )
        msgs = await ConversationRepo.list_messages(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        return conv, msgs

    @staticmethod
    async def take_thread(
        session: AsyncSession,
        *,
        principal: Principal,
        conversation_id: UUID,
    ) -> ConversationRow:
        conv = await ConversationRepo.get_for_principal(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        if conv is None or not _staff_can_access(principal, conv):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Conversation Not Found",
                detail="The requested conversation was not found.",
                status_code=404,
            )

        won = await InboxRepo.atomic_take(
            session,
            org_id=principal.org_id,
            conversation_id=conversation_id,
            staff_user_id=principal.user_id,
        )
        if not won:
            raise AppError(
                code=ErrorCode.CONFLICT_TAKEN,
                title="Conversation Already Taken",
                detail="Another staff member has already taken this conversation.",
                status_code=409,
            )

        await AuditService.record(
            session,
            principal=principal,
            action="inbox.take",
            target_type="conversation",
            target_id=str(conversation_id),
            outcome="staff",
        )
        updated = await ConversationRepo.get_for_principal(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        if updated is None:
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Conversation Not Found",
                detail="The requested conversation was not found.",
                status_code=404,
            )
        return updated

    @staticmethod
    async def release_thread(
        session: AsyncSession,
        *,
        principal: Principal,
        conversation_id: UUID,
    ) -> ConversationRow:
        conv = await ConversationRepo.get_for_principal(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        if conv is None or not _staff_can_access(principal, conv):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Conversation Not Found",
                detail="The requested conversation was not found.",
                status_code=404,
            )
        await InboxRepo.release_to_ai(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        await AuditService.record(
            session,
            principal=principal,
            action="inbox.release",
            target_type="conversation",
            target_id=str(conversation_id),
            outcome="ai",
        )
        updated = await ConversationRepo.get_for_principal(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        if updated is None:
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Conversation Not Found",
                detail="The requested conversation was not found.",
                status_code=404,
            )
        return updated

    @staticmethod
    async def send_staff_reply(
        session: AsyncSession,
        *,
        principal: Principal,
        conversation_id: UUID,
        content: str,
    ) -> MessageRow:
        conv = await ConversationRepo.get_for_principal(
            session, org_id=principal.org_id, conversation_id=conversation_id
        )
        if conv is None or not _staff_can_access(principal, conv):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Conversation Not Found",
                detail="The requested conversation was not found.",
                status_code=404,
            )
        return await ConversationRepo.append_message(
            session,
            org_id=principal.org_id,
            conversation_id=conversation_id,
            sender_role="staff",
            content=content,
        )
