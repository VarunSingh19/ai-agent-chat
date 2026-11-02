"""Idempotent document ingestion job (Architecture.md §7g)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.knowledge.ingest.chunk import chunk_extracted_pages
from pdagent.knowledge.ingest.embed import EmbeddingClient
from pdagent.knowledge.ingest.extract import IngestionExtractionError, extract_document_pages
from pdagent.knowledge.repo import KnowledgeRepo


async def run_document_ingestion_job(
    session: AsyncSession,
    *,
    org_id: UUID,
    document_id: UUID,
    content_bytes: bytes,
    content_type: str = "text/plain",
    embedder: EmbeddingClient | None = None,
) -> int:
    """Extract, chunk, embed, and store chunks idempotently for `(org_id, document_id)`."""
    client = embedder or EmbeddingClient()
    doc = await KnowledgeRepo.get_document(session, org_id=org_id, document_id=document_id)
    if doc is None:
        return 0

    existing_chunks = await KnowledgeRepo.list_chunks_for_document(
        session, org_id=org_id, document_id=document_id
    )
    if existing_chunks and doc.status == "ready":
        # Idempotent: unchanged ready document with existing chunks is never re-embedded
        return len(existing_chunks)

    try:
        pages = extract_document_pages(content_bytes, content_type=content_type)
        candidates = chunk_extracted_pages(pages)
        embeddings = await client.embed_texts([c.content for c in candidates])
    except IngestionExtractionError as exc:
        await KnowledgeRepo.mark_document_failed(
            session, org_id=org_id, document_id=document_id, reason_code=exc.reason_code
        )
        return 0

    await KnowledgeRepo.replace_document_chunks(
        session,
        org_id=org_id,
        property_id=doc.property_id,
        document_id=document_id,
        candidates=candidates,
        embeddings=embeddings,
    )
    return len(candidates)
