"""FastAPI router for `/v1/knowledge/documents` (Architecture.md §8, Phase 3)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.auth.deps import get_tenant_session, require_roles
from pdagent.auth.principal import Principal
from pdagent.knowledge.service import KnowledgeService

router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"])


class DocumentUploadRequest(BaseModel):
    """Payload for uploading or pasting FAQ/knowledge document text."""

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=500_000)
    content_type: str = Field(default="text/plain", max_length=128)
    property_id: UUID | None = None


class DocumentResponse(BaseModel):
    """Public representation of a tenant knowledge document (embeddings never returned)."""

    id: str
    title: str
    property_id: str | None
    version: int
    status: str
    failure_reason: str | None = None
    created_at: str


@router.post("/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: DocumentUploadRequest,
    principal: Principal = Depends(require_roles("org_admin", "pm_member")),
    session: AsyncSession = Depends(get_tenant_session),
) -> DocumentResponse:
    """Upload and ingest a knowledge document for the caller's organisation."""
    doc = await KnowledgeService.upload_and_ingest(
        session,
        principal=principal,
        title=payload.title,
        content_bytes=payload.content.encode("utf-8"),
        content_type=payload.content_type,
        property_id=payload.property_id,
    )
    return DocumentResponse(
        id=str(doc.id),
        title=doc.title,
        property_id=str(doc.property_id) if doc.property_id else None,
        version=doc.version,
        status=doc.status,
        failure_reason=doc.failure_reason,
        created_at=doc.created_at.isoformat(),
    )


@router.get("/documents", response_model=dict[str, object])
async def list_documents(
    property_id: UUID | None = None,
    principal: Principal = Depends(require_roles("org_admin", "pm_member", "tenant")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict[str, object]:
    """List ready/processing knowledge documents visible to the caller."""
    docs = await KnowledgeService.list_documents(
        session, principal=principal, property_id=property_id
    )
    items = [
        DocumentResponse(
            id=str(d.id),
            title=d.title,
            property_id=str(d.property_id) if d.property_id else None,
            version=d.version,
            status=d.status,
            failure_reason=d.failure_reason,
            created_at=d.created_at.isoformat(),
        ).model_dump()
        for d in docs
    ]
    return {"items": items, "next_cursor": None}


@router.post("/documents/{document_id}/replace", response_model=DocumentResponse)
async def replace_document(
    document_id: UUID,
    payload: DocumentUploadRequest,
    principal: Principal = Depends(require_roles("org_admin", "pm_member")),
    session: AsyncSession = Depends(get_tenant_session),
) -> DocumentResponse:
    """Replace an existing document version and purge old chunks immediately."""
    doc = await KnowledgeService.replace_document(
        session,
        principal=principal,
        old_document_id=document_id,
        title=payload.title,
        content_bytes=payload.content.encode("utf-8"),
        content_type=payload.content_type,
    )
    return DocumentResponse(
        id=str(doc.id),
        title=doc.title,
        property_id=str(doc.property_id) if doc.property_id else None,
        version=doc.version,
        status=doc.status,
        failure_reason=doc.failure_reason,
        created_at=doc.created_at.isoformat(),
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID,
    principal: Principal = Depends(require_roles("org_admin", "pm_member")),
    session: AsyncSession = Depends(get_tenant_session),
) -> Response:
    """Delete a knowledge document and remove all of its indexed chunks."""
    await KnowledgeService.delete_document(session, principal=principal, document_id=document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
