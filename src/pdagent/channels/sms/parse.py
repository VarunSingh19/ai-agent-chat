"""SMS compliance keyword parser (`STOP`/`START`) and phone
hashing (Phase 8, Rules.md §1 Rule 7)."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

SmsCommand = Literal["opt_out", "opt_in", "message"]

_STOP_KEYWORDS: frozenset[str] = frozenset(
    {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
)
_START_KEYWORDS: frozenset[str] = frozenset({"start", "unstop", "yes"})
_DIGITS_RE = re.compile(r"\D+")


def hash_phone_number(raw_phone: str) -> str:
    """Compute a deterministic SHA-256 hex digest of a normalized phone number (never log raw
    phone).
    """
    digits = _DIGITS_RE.sub("", raw_phone.strip())
    return hashlib.sha256(f"pdk-phone:{digits}".encode()).hexdigest()


def parse_sms_compliance_command(body: str) -> SmsCommand:
    """Classify an inbound SMS body as `opt_out` (`STOP`), `opt_in`
    (`START`), or normal `message`."""
    cleaned = body.strip().lower()
    if cleaned in _STOP_KEYWORDS:
        return "opt_out"
    if cleaned in _START_KEYWORDS:
        return "opt_in"
    return "message"
