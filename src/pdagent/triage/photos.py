"""Photo validation, short-lived signed URLs, and image token cost calculation (Phase 9)."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pdagent.core.errors import AppError, ErrorCode
from pdagent.triage.schemas import PhotoDescriptor

ALLOWED_IMAGE_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_PHOTOS_PER_TRIAGE = 4
MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024


def validate_photos(photos: list[PhotoDescriptor]) -> None:
    """Validate count, MIME type, and byte size of triage photos."""
    if len(photos) > MAX_PHOTOS_PER_TRIAGE:
        raise AppError(
            code=ErrorCode.VALIDATION,
            title="Too Many Photos",
            detail=f"At most {MAX_PHOTOS_PER_TRIAGE} photos may be attached to a triage request.",
            status_code=422,
        )
    for photo in photos:
        if photo.content_type.lower() not in ALLOWED_IMAGE_TYPES:
            raise AppError(
                code=ErrorCode.VALIDATION,
                title="Unsupported Photo Format",
                detail="Photos must be JPEG, PNG, or WebP.",
                status_code=422,
            )
        if photo.size_bytes > MAX_PHOTO_SIZE_BYTES:
            raise AppError(
                code=ErrorCode.VALIDATION,
                title="Photo Too Large",
                detail="Each photo must be 5 MB or smaller.",
                status_code=422,
            )


def estimate_image_tokens_and_cost(
    photos: list[PhotoDescriptor],
    *,
    input_per_1m_usd: float = 2.00,
) -> tuple[int, float]:
    """Calculate image token count (`(width * height) // 750`) and USD cost on the large/triage
    slot.
    """
    total_tokens = 0
    for photo in photos:
        tokens = max(256, (photo.width_px * photo.height_px) // 750)
        total_tokens += tokens
    cost_usd = round((total_tokens / 1_000_000.0) * input_per_1m_usd, 8)
    return total_tokens, cost_usd


def build_signed_photo_url(
    *,
    org_id: UUID,
    object_key: str,
    signing_key: str = "pdk-media-signing-key",
    ttl_seconds: int = 300,
) -> str:
    """Build a short-lived (5-minute) signed read URL for staff inbox review (Rules.md §5 LLM02)."""
    expires_ts = int((datetime.now(UTC) + timedelta(seconds=ttl_seconds)).timestamp())
    msg = f"{org_id}:{object_key}:{expires_ts}".encode()
    sig = hmac.new(signing_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:24]
    return f"https://media.propertydek.example.com/{org_id}/{object_key}?exp={expires_ts}&sig={sig}"
