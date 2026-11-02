"""Structured JSON logging with mandatory PII and secret masking (Rules.md §1 rule 7 & §7).

Never logs message text, phone numbers, emails, payment references, tokens, or tool arguments.
There is no configuration flag to disable masking.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Final

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
org_hash_var: contextvars.ContextVar[str] = contextvars.ContextVar("org_hash", default="")

# Keys whose values must never be emitted in log records or structured payloads (Rules.md §1 rule 7)
FORBIDDEN_LOG_KEYS: Final[frozenset[str]] = frozenset(
    {
        "content",
        "message_text",
        "user_message",
        "assistant_message",
        "prompt",
        "messages",
        "text",
        "body",
        "args",
        "tool_args",
        "arguments",
        "phone",
        "phone_number",
        "email",
        "token",
        "chat_token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "password",
        "secret",
        "payment_ref",
        "payment_reference",
    }
)

_BEARER_RE: Final[re.Pattern[str]] = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*")
_JWT_RE: Final[re.Pattern[str]] = re.compile(
    r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"
)
_API_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:sk-ant-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{12,})\b"
)
_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
_PHONE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!\w)(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}\b|\+\d{10,15}\b"
)
_PAYMENT_REF_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:pay|ch|pi|re|txn)_[A-Za-z0-9]{8,}\b")


def hash_identifier(raw_id: str) -> str:
    """Return a short non-reversible SHA-256 prefix for correlation (Architecture.md §9)."""
    if not raw_id:
        return ""
    return hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]


def mask_sensitive_text(value: str) -> str:
    """Redact tokens, API keys, emails, phone numbers, and payment references from text."""
    masked = _BEARER_RE.sub("Bearer [REDACTED_TOKEN]", value)
    masked = _JWT_RE.sub("[REDACTED_JWT]", masked)
    masked = _API_KEY_RE.sub("[REDACTED_API_KEY]", masked)
    masked = _EMAIL_RE.sub("[REDACTED_EMAIL]", masked)
    masked = _PHONE_RE.sub("[REDACTED_PHONE]", masked)
    return _PAYMENT_REF_RE.sub("[REDACTED_PAYMENT_REF]", masked)


sanitize_log_text = mask_sensitive_text


def sanitize_log_value(key: str | None, value: object) -> object:
    """Recursively sanitize a value for safe structured logging."""
    if key is not None and key.lower() in FORBIDDEN_LOG_KEYS:
        return "[REDACTED_PII]"
    if isinstance(value, str):
        return mask_sensitive_text(value)
    if isinstance(value, dict):
        return {str(k): sanitize_log_value(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_log_value(key, item) for item in value]
    return value


# Standard LogRecord attributes that must not be treated as user-supplied extra keys
_STD_RECORD_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "name",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "msg",
        "args",
    }
)


class PiiMaskingFilter(logging.Filter):
    """Logging filter that enforces PII and secret scrubbing on every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_sensitive_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: sanitize_log_value(k, v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(sanitize_log_value(None, a) for a in record.args)

        for attr_name in list(vars(record).keys()):
            if attr_name in _STD_RECORD_ATTRS:
                continue
            attr_val = getattr(record, attr_name)
            if attr_name.lower() in FORBIDDEN_LOG_KEYS:
                setattr(record, attr_name, "[REDACTED_PII]")
            elif isinstance(attr_val, (str, dict, list, tuple)):
                setattr(record, attr_name, sanitize_log_value(attr_name, attr_val))
        return True


class StructuredJsonFormatter(logging.Formatter):
    """Format log records as single-line JSON with safe operational metadata only."""

    _ALLOWED_EXTRA_FIELDS: Final[tuple[str, ...]] = (
        "request_id",
        "org_hash",
        "route",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "cost_usd",
        "latency_ms",
        "ttft_ms",
        "failover",
        "status_code",
        "error_code",
    )

    def format(self, record: logging.LogRecord) -> str:
        message = mask_sensitive_text(record.getMessage())
        req_id = getattr(record, "request_id", "") or request_id_var.get()
        org_hash = getattr(record, "org_hash", "") or org_hash_var.get()

        payload: dict[str, object] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": message,
            "request_id": req_id,
        }
        if org_hash:
            payload["org_hash"] = org_hash

        for field in self._ALLOWED_EXTRA_FIELDS:
            if field in {"request_id", "org_hash"}:
                continue
            if hasattr(record, field):
                payload[field] = sanitize_log_value(field, getattr(record, field))

        if record.exc_info and record.exc_info[0] is not None:
            exc_type = record.exc_info[0].__name__
            exc_val = mask_sensitive_text(str(record.exc_info[1] or ""))
            payload["exception"] = {"type": exc_type, "detail": exc_val}

        return json.dumps(payload, sort_keys=True)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure root logger with PiiMaskingFilter and StructuredJsonFormatter."""
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    handler = logging.StreamHandler()
    handler.addFilter(PiiMaskingFilter())
    handler.setFormatter(StructuredJsonFormatter())

    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.filters.clear()
    root_logger.addFilter(PiiMaskingFilter())
