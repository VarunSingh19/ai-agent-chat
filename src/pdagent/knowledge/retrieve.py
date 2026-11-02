"""Hybrid retrieval with Reciprocal Rank Fusion (`k=60`) and full-text fallback (Architecture.md
§7b).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from pdagent.agent.context import RetrievedChunkItem
from pdagent.auth.principal import Principal
from pdagent.knowledge.ingest.embed import EmbeddingClient, cosine_similarity
from pdagent.knowledge.repo import KnowledgeRepo

RRF_K = 60


@dataclass(frozen=True, slots=True)
class RetrievalOutcome:
    """Result of a hybrid knowledge retrieval query."""

    chunks: list[RetrievedChunkItem]
    degraded_retrieval: bool = False


def _lexical_overlap_score(query: str, text_content: str, heading: str) -> float:
    q_terms = {
        tok.strip(".,!?;:\"'()[]{}").lower()
        for tok in query.split()
        if len(tok.strip(".,!?;:\"'()[]{}")) >= 3
    }
    if not q_terms:
        return 0.0
    haystack = f"{heading} {text_content}".lower()
    hits = sum(1 for term in q_terms if term in haystack)
    return hits / len(q_terms)


async def retrieve_knowledge_chunks(
    session: AsyncSession,
    *,
    principal: Principal,
    query: str,
    top_k: int = 5,
    embedder: EmbeddingClient | None = None,
) -> RetrievalOutcome:
    """Retrieve top-k chunks scoped to `principal` using Hybrid Search + RRF (`k=60`).

    Per Architecture.md §7b & Rules.md §5 LLM09:
    1. Pre-filter in SQL by `org_id`, `principal.property_ids`, and `status='ready'`.
    2. Compute full-text lexical ranking (top 30) and vector similarity ranking (top 30).
    3. Fuse with Reciprocal Rank Fusion (`k = 60`).
    4. If embedding provider fails, fall back to full-text and set `degraded_retrieval=True`.
    """
    scoped_rows = await KnowledgeRepo.list_ready_chunks_for_scope(
        session,
        org_id=principal.org_id,
        allowed_property_ids=principal.property_ids,
        is_org_admin=(principal.role == "org_admin"),
    )
    if not scoped_rows:
        return RetrievalOutcome(chunks=[], degraded_retrieval=False)

    client = embedder or EmbeddingClient()
    degraded = False
    query_vec: list[float] | None = None
    try:
        query_vec = await client.embed_query(query)
    except Exception:
        degraded = True

    lexical_scored: list[tuple[float, int]] = []
    vector_scored: list[tuple[float, int]] = []

    for idx, (chunk_row, doc_row) in enumerate(scoped_rows):
        lex_score = _lexical_overlap_score(
            query, chunk_row.content, f"{doc_row.title} {chunk_row.heading_path}"
        )
        if lex_score > 0.0:
            lexical_scored.append((lex_score, idx))
        if query_vec is not None and chunk_row.embedding_json:
            vec_score = cosine_similarity(query_vec, chunk_row.embedding_json)
            if vec_score > 0.0:
                vector_scored.append((vec_score, idx))

    lexical_scored.sort(key=lambda item: item[0], reverse=True)
    vector_scored.sort(key=lambda item: item[0], reverse=True)

    lexical_top = lexical_scored[:30]
    vector_top = vector_scored[:30]

    rrf_scores: dict[int, float] = {}
    for rank, (_score, row_idx) in enumerate(lexical_top, start=1):
        rrf_scores[row_idx] = rrf_scores.get(row_idx, 0.0) + (1.0 / (RRF_K + rank))

    if not degraded:
        for rank, (_score, row_idx) in enumerate(vector_top, start=1):
            rrf_scores[row_idx] = rrf_scores.get(row_idx, 0.0) + (1.0 / (RRF_K + rank))

    ranked_indices = sorted(rrf_scores.keys(), key=lambda i: rrf_scores[i], reverse=True)[:top_k]
    items: list[RetrievedChunkItem] = []
    for idx in ranked_indices:
        chunk_row, doc_row = scoped_rows[idx]
        items.append(
            RetrievedChunkItem(
                document_id=str(doc_row.id),
                title=doc_row.title,
                heading_path=chunk_row.heading_path,
                content=chunk_row.content,
                page_number=chunk_row.page_number,
            )
        )

    return RetrievalOutcome(chunks=items, degraded_retrieval=degraded)
