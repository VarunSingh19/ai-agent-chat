"""Document text extraction for PDF, DOCX, and plain text
(Architecture.md §7g, Rules.md §2 & §3)."""

from __future__ import annotations

import io
from dataclasses import dataclass

import docx
from pypdf import PdfReader


class IngestionExtractionError(ValueError):
    """Raised when a document cannot be extracted (e.g., scanned PDF with no text layer)."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    """Extracted text for a single document page or section."""

    page_number: int
    text: str


MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PDF_PAGES = 100


def extract_document_pages(
    content_bytes: bytes,
    *,
    content_type: str = "text/plain",
) -> list[ExtractedPage]:
    """Extract text pages from plain text, Markdown, PDF (`pypdf`), or DOCX (`python-docx`)."""
    if len(content_bytes) > MAX_UPLOAD_BYTES:
        raise IngestionExtractionError("FILE_TOO_LARGE", "Document exceeds 10 MB upload limit.")
    if not content_bytes:
        raise IngestionExtractionError("EMPTY_DOCUMENT", "Uploaded document is empty.")

    normalized_type = content_type.lower().split(";")[0].strip()

    if normalized_type in ("text/plain", "text/markdown"):
        try:
            text_str = content_bytes.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise IngestionExtractionError("INVALID_ENCODING", "Text must be valid UTF-8.") from exc
        if not text_str:
            raise IngestionExtractionError("EMPTY_DOCUMENT", "Text document contains no text.")
        return [ExtractedPage(page_number=1, text=text_str)]

    if normalized_type == "application/pdf":
        try:
            reader = PdfReader(io.BytesIO(content_bytes))
        except Exception as exc:
            raise IngestionExtractionError(
                "UNREADABLE_PDF", "PDF file could not be parsed."
            ) from exc

        if len(reader.pages) > MAX_PDF_PAGES:
            raise IngestionExtractionError("TOO_MANY_PAGES", "PDF exceeds 100-page limit.")

        pages: list[ExtractedPage] = []
        for idx, page in enumerate(reader.pages, start=1):
            extracted = (page.extract_text() or "").strip()
            if extracted:
                pages.append(ExtractedPage(page_number=idx, text=extracted))
        if not pages:
            raise IngestionExtractionError(
                "SCANNED_PDF_UNSUPPORTED",
                "PDF contains no embedded text layer; scanned PDFs are unsupported in v1.",
            )
        return pages

    if normalized_type in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/docx",
    ):
        try:
            doc = docx.Document(io.BytesIO(content_bytes))
        except Exception as exc:
            raise IngestionExtractionError(
                "UNREADABLE_DOCX", "DOCX file could not be parsed."
            ) from exc
        paragraphs = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        if not paragraphs:
            raise IngestionExtractionError("EMPTY_DOCUMENT", "DOCX contains no readable text.")
        return [ExtractedPage(page_number=1, text="\n\n".join(paragraphs))]

    raise IngestionExtractionError("UNSUPPORTED_MEDIA_TYPE", f"Unsupported type: {normalized_type}")
