"""SQLAlchemy models and repository for tenant documents and chunks (Phase 3, Rules.md §5 LLM09)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, delete, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pdagent.core.db import Base
from pdagent.core.ids import new_id, utc_now
from pdagent.core.rls import verify_rls_context
from pdagent.knowledge.ingest.chunk import ChunkCandidate


class DocumentRow(Base):
    """Knowledge document record (`documents` table with RLS)."""

    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    property_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    failure_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class DocumentChunkRow(Base):
    """Chunked & embedded knowledge slice (`document_chunks` table with RLS)."""

    __tablename__ = "document_chunks"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    property_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_json: Mapped[list[float]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class KnowledgeRepo:
    """Data access layer for `documents` and `document_chunks` enforcing RLS context."""

    @staticmethod
    async def create_document(
        session: AsyncSession,
        *,
        org_id: UUID,
        property_id: UUID | None,
        title: str,
        sha256: str,
        version: int = 1,
        status: str = "processing",
    ) -> DocumentRow:
        await verify_rls_context(session)
        row = DocumentRow(
            id=new_id(),
            org_id=org_id,
            property_id=property_id,
            title=title,
            sha256=sha256,
            version=version,
            status=status,
            created_at=utc_now(),
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def get_document(
        session: AsyncSession,
        *,
        org_id: UUID,
        document_id: UUID,
    ) -> DocumentRow | None:
        await verify_rls_context(session)
        stmt = select(DocumentRow).where(
            DocumentRow.org_id == org_id,
            DocumentRow.id == document_id,
            DocumentRow.status != "deleted",
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def list_documents(
        session: AsyncSession,
        *,
        org_id: UUID,
        property_id: UUID | None = None,
    ) -> list[DocumentRow]:
        await verify_rls_context(session)
        stmt = select(DocumentRow).where(
            DocumentRow.org_id == org_id,
            DocumentRow.status != "deleted",
        )
        if property_id is not None:
            stmt = stmt.where(DocumentRow.property_id == property_id)
        stmt = stmt.order_by(DocumentRow.created_at.desc())
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def mark_document_failed(
        session: AsyncSession,
        *,
        org_id: UUID,
        document_id: UUID,
        reason_code: str,
    ) -> None:
        await verify_rls_context(session)
        await session.execute(
            update(DocumentRow)
            .where(DocumentRow.org_id == org_id, DocumentRow.id == document_id)
            .values(status="failed", failure_reason=reason_code)
        )

    @staticmethod
    async def replace_document_chunks(
        session: AsyncSession,
        *,
        org_id: UUID,
        property_id: UUID | None,
        document_id: UUID,
        candidates: list[ChunkCandidate],
        embeddings: list[list[float]],
    ) -> None:
        await verify_rls_context(session)
        await session.execute(
            delete(DocumentChunkRow).where(
                DocumentChunkRow.org_id == org_id,
                DocumentChunkRow.document_id == document_id,
            )
        )
        for cand, emb in zip(candidates, embeddings, strict=True):
            session.add(
                DocumentChunkRow(
                    id=new_id(),
                    org_id=org_id,
                    property_id=property_id,
                    document_id=document_id,
                    chunk_index=cand.chunk_index,
                    heading_path=cand.heading_path,
                    page_number=cand.page_number,
                    content=cand.content,
                    embedding_json=emb,
                    created_at=utc_now(),
                )
            )
        await session.execute(
            update(DocumentRow)
            .where(DocumentRow.org_id == org_id, DocumentRow.id == document_id)
            .values(status="ready", failure_reason=None)
        )
        await session.flush()

    @staticmethod
    async def mark_replaced_and_purge_chunks(
        session: AsyncSession,
        *,
        org_id: UUID,
        old_document_id: UUID,
    ) -> None:
        """Mark an older document version `replaced` and remove its chunks (Rules.md §5 LLM09)."""
        await verify_rls_context(session)
        await session.execute(
            delete(DocumentChunkRow).where(
                DocumentChunkRow.org_id == org_id,
                DocumentChunkRow.document_id == old_document_id,
            )
        )
        await session.execute(
            update(DocumentRow)
            .where(DocumentRow.org_id == org_id, DocumentRow.id == old_document_id)
            .values(status="replaced")
        )

    @staticmethod
    async def soft_delete_document(
        session: AsyncSession,
        *,
        org_id: UUID,
        document_id: UUID,
    ) -> bool:
        await verify_rls_context(session)
        doc = await KnowledgeRepo.get_document(session, org_id=org_id, document_id=document_id)
        if doc is None:
            return False
        await session.execute(
            delete(DocumentChunkRow).where(
                DocumentChunkRow.org_id == org_id,
                DocumentChunkRow.document_id == document_id,
            )
        )
        await session.execute(
            update(DocumentRow)
            .where(DocumentRow.org_id == org_id, DocumentRow.id == document_id)
            .values(status="deleted")
        )
        return True

    @staticmethod
    async def list_chunks_for_document(
        session: AsyncSession,
        *,
        org_id: UUID,
        document_id: UUID,
    ) -> list[DocumentChunkRow]:
        await verify_rls_context(session)
        stmt = (
            select(DocumentChunkRow)
            .where(
                DocumentChunkRow.org_id == org_id,
                DocumentChunkRow.document_id == document_id,
            )
            .order_by(DocumentChunkRow.chunk_index.asc())
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def list_ready_chunks_for_scope(
        session: AsyncSession,
        *,
        org_id: UUID,
        allowed_property_ids: tuple[UUID, ...],
        is_org_admin: bool = False,
    ) -> list[tuple[DocumentChunkRow, DocumentRow]]:
        """Filter chunks in SQL by `org_id`, `property_id` scope,
        and `document.status = 'ready'`."""
        await verify_rls_context(session)
        stmt = (
            select(DocumentChunkRow, DocumentRow)
            .join(DocumentRow, DocumentChunkRow.document_id == DocumentRow.id)
            .where(
                DocumentChunkRow.org_id == org_id,
                DocumentRow.org_id == org_id,
                DocumentRow.status == "ready",
            )
        )
        if not is_org_admin:
            if allowed_property_ids:
                stmt = stmt.where(
                    (DocumentChunkRow.property_id.is_(None))
                    | (DocumentChunkRow.property_id.in_(allowed_property_ids))
                )
            else:
                stmt = stmt.where(DocumentChunkRow.property_id.is_(None))
        res = await session.execute(stmt)
        return [(row[0], row[1]) for row in res.all()]
