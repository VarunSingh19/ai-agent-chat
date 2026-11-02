"""Heading-aware document chunker with overlap (Architecture.md §7b)."""

from __future__ import annotations

from dataclasses import dataclass

from pdagent.knowledge.ingest.extract import ExtractedPage


@dataclass(frozen=True, slots=True)
class ChunkCandidate:
    """A single heading-scoped chunk ready for embedding and indexing."""

    chunk_index: int
    heading_path: str
    page_number: int | None
    content: str


def chunk_extracted_pages(
    pages: list[ExtractedPage],
    *,
    target_words: int = 350,
    overlap_words: int = 40,
) -> list[ChunkCandidate]:
    """Split extracted pages on headings and word budgets while preserving `heading_path`."""
    candidates: list[ChunkCandidate] = []
    current_heading = "General"
    chunk_idx = 0

    for page in pages:
        lines = page.text.splitlines()
        buffer_words: list[str] = []

        def _flush_buffer(page_num: int, heading: str) -> None:
            nonlocal chunk_idx, buffer_words
            if not buffer_words:
                return
            text_body = " ".join(buffer_words).strip()
            if text_body:
                candidates.append(
                    ChunkCandidate(
                        chunk_index=chunk_idx,
                        heading_path=heading,
                        page_number=page_num,
                        content=text_body,
                    )
                )
                chunk_idx += 1
            buffer_words = buffer_words[-overlap_words:] if overlap_words > 0 else []

        for raw_line in lines:
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                if buffer_words:
                    _flush_buffer(page.page_number, current_heading)
                    buffer_words = []
                current_heading = stripped.lstrip("#").strip() or current_heading
                continue

            words = stripped.split()
            buffer_words.extend(words)
            if len(buffer_words) >= target_words:
                _flush_buffer(page.page_number, current_heading)

        if buffer_words:
            _flush_buffer(page.page_number, current_heading)
            buffer_words = []

    return candidates
