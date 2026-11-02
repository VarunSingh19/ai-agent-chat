"""Knowledge Base service for document upload, replacement, deletion, and retrieval (Phase 3)."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.auth.principal import Principal
from pdagent.core.errors import AppError, ErrorCode
from pdagent.knowledge.ingest.embed import EmbeddingClient
from pdagent.knowledge.ingest.jobs import run_document_ingestion_job
from pdagent.knowledge.repo import DocumentRow, KnowledgeRepo


class KnowledgeService:
    """Service layer for `knowledge/` enforcing role and property-scope authorization."""

    @staticmethod
    async def upload_and_ingest(
        session: AsyncSession,
        *,
        principal: Principal,
        title: str,
        content_bytes: bytes,
        content_type: str = "text/plain",
        property_id: UUID | None = None,
        version: int = 1,
        embedder: EmbeddingClient | None = None,
    ) -> DocumentRow:
        """Create a document row and run idempotent ingestion within the tenant transaction."""
        if property_id is not None and not principal.can_access_property(property_id):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Property Not Found",
                detail="The specified property was not found.",
                status_code=404,
            )

        digest = hashlib.sha256(content_bytes).hexdigest()
        doc = await KnowledgeRepo.create_document(
            session,
            org_id=principal.org_id,
            property_id=property_id,
            title=title.strip() or "Untitled Document",
            sha256=digest,
            version=version,
            status="processing",
        )
        await run_document_ingestion_job(
            session,
            org_id=principal.org_id,
            document_id=doc.id,
            content_bytes=content_bytes,
            content_type=content_type,
            embedder=embedder,
        )
        refreshed = await KnowledgeRepo.get_document(
            session, org_id=principal.org_id, document_id=doc.id
        )
        if refreshed is None:
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Document Not Found",
                detail="Document was not found after ingestion.",
                status_code=404,
            )
        return refreshed

    @staticmethod
    async def replace_document(
        session: AsyncSession,
        *,
        principal: Principal,
        old_document_id: UUID,
        title: str,
        content_bytes: bytes,
        content_type: str = "text/plain",
        embedder: EmbeddingClient | None = None,
    ) -> DocumentRow:
        """Replace an existing document, marking the previous version `replaced` and purging its
        chunks.
        """
        old_doc = await KnowledgeRepo.get_document(
            session, org_id=principal.org_id, document_id=old_document_id
        )
        if old_doc is None or not principal.can_access_property(old_doc.property_id):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Document Not Found",
                detail="The requested document was not found.",
                status_code=404,
            )

        await KnowledgeRepo.mark_replaced_and_purge_chunks(
            session, org_id=principal.org_id, old_document_id=old_doc.id
        )
        return await KnowledgeService.upload_and_ingest(
            session,
            principal=principal,
            title=title.strip() or old_doc.title,
            content_bytes=content_bytes,
            content_type=content_type,
            property_id=old_doc.property_id,
            version=old_doc.version + 1,
            embedder=embedder,
        )

    @staticmethod
    async def list_documents(
        session: AsyncSession,
        *,
        principal: Principal,
        property_id: UUID | None = None,
    ) -> list[DocumentRow]:
        docs = await KnowledgeRepo.list_documents(
            session, org_id=principal.org_id, property_id=property_id
        )
        return [d for d in docs if principal.can_access_property(d.property_id)]

    @staticmethod
    async def delete_document(
        session: AsyncSession,
        *,
        principal: Principal,
        document_id: UUID,
    ) -> None:
        doc = await KnowledgeRepo.get_document(
            session, org_id=principal.org_id, document_id=document_id
        )
        if doc is None or not principal.can_access_property(doc.property_id):
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                title="Document Not Found",
                detail="The requested document was not found.",
                status_code=404,
            )
        await KnowledgeRepo.soft_delete_document(
            session, org_id=principal.org_id, document_id=document_id
        )
