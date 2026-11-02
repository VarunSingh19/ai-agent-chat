"""UUIDv7 and UTC time helpers (Architecture.md §5 & §8, Rules.md §4)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def new_uuid7() -> uuid.UUID:
    """Generate a new time-ordered UUIDv7 using Python 3.14 stdlib uuid.uuid7."""
    return uuid.uuid7()


def new_id() -> uuid.UUID:
    """Alias for new_uuid7() used across domain repositories and services."""
    return uuid.uuid7()


def new_uuid7_str() -> str:
    """Generate a new UUIDv7 formatted as a canonical lowercase string."""
    return str(uuid.uuid7())


def utc_now() -> datetime:
    """Return current timezone-aware UTC datetime (Rules.md §4)."""
    return datetime.now(tz=UTC)


def extract_uuid7_timestamp(value: uuid.UUID) -> datetime:
    """Extract the embedded millisecond UTC timestamp from a UUIDv7."""
    if value.version != 7:
        msg = f"Expected UUIDv7, got version {value.version}"
        raise ValueError(msg)
    unix_ts_ms = value.int >> 80
    return datetime.fromtimestamp(unix_ts_ms / 1000.0, tz=UTC)
