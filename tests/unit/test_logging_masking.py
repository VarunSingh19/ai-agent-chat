"""Unit tests for PII masking in logs and OpenTelemetry spans (Rules.md §1 rule 7 & §5)."""

from __future__ import annotations

import json
import logging

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pdagent.core.logging import (
    PiiMaskingFilter,
    StructuredJsonFormatter,
    configure_logging,
    hash_identifier,
    mask_sensitive_text,
    sanitize_log_value,
)
from pdagent.core.settings import Settings
from pdagent.core.telemetry import configure_telemetry, sanitize_span_attributes


def test_mask_sensitive_text_redacts_all_pii_patterns() -> None:
    raw = (
        "Tenant jane.doe@example.org called from (415) 555-0199 with token "
        "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTYifQ.c2lnbmF0dXJl "
        "and key sk-ant-api03-secretkey123456 and payment pay_9876543210abcdef"
    )
    masked = mask_sensitive_text(raw)

    assert "jane.doe@example.org" not in masked
    assert "415" not in masked
    assert "555-0199" not in masked
    assert "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9" not in masked
    assert "sk-ant-api03" not in masked
    assert "pay_9876543210abcdef" not in masked
    assert "[REDACTED_EMAIL]" in masked
    assert "[REDACTED_PHONE]" in masked
    assert "[REDACTED_TOKEN]" in masked
    assert "[REDACTED_API_KEY]" in masked
    assert "[REDACTED_PAYMENT_REF]" in masked
    assert hash_identifier("") == ""
    assert len(hash_identifier("org-123")) == 16


def test_sanitize_log_value_drops_forbidden_keys_and_handles_lists() -> None:
    payload = {
        "content": "My apartment smells like gas in unit 3B",
        "phone": "+14155550199",
        "email": "resident@building.com",
        "args": {"unit_id": "3B", "description": "leaking pipe"},
        "token": "secret-jwt-token",
        "route": "small",
        "items": ["call 415-555-0199", 42],
        "nested": {
            "tool_args": {"amount": 500},
            "note": "Contact admin@propertydek.com",
        },
    }
    cleaned = sanitize_log_value(None, payload)
    assert isinstance(cleaned, dict)
    assert cleaned["content"] == "[REDACTED_PII]"
    assert cleaned["phone"] == "[REDACTED_PII]"
    assert cleaned["email"] == "[REDACTED_PII]"
    assert cleaned["args"] == "[REDACTED_PII]"
    assert cleaned["token"] == "[REDACTED_PII]"
    assert cleaned["route"] == "small"
    items = cleaned["items"]
    assert isinstance(items, list)
    assert "415-555-0199" not in str(items[0])
    nested = cleaned["nested"]
    assert isinstance(nested, dict)
    assert nested["tool_args"] == "[REDACTED_PII]"
    assert "admin@propertydek.com" not in str(nested["note"])


def test_structured_json_formatter_and_filter_never_emit_pii() -> None:
    configure_logging()
    logger = logging.getLogger("pdagent.test.masking")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    records: list[str] = []

    class ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    handler = ListHandler()
    handler.addFilter(PiiMaskingFilter())
    handler.setFormatter(StructuredJsonFormatter())
    logger.addHandler(handler)

    logger.info(
        "Turn completed for %s phone %s",
        "tenant@example.com",
        "212-555-0144",
        extra={
            "request_id": "0192e500-0000-7000-8000-000000000001",
            "org_hash": hash_identifier("org-uuid-123"),
            "route": "small",
            "model": "claude-haiku-5-5",
            "input_tokens": 600,
            "output_tokens": 80,
            "cache_read_tokens": 512,
            "reasoning_tokens": 0,
            "cost_usd": "0.000105",
            "content": "My sink is clogged, please help!",
            "tool_args": {"description": "sink clogged"},
            "custom_note": "Email resident@example.com",
        },
    )

    assert len(records) == 1
    parsed = json.loads(records[0])
    assert "tenant@example.com" not in records[0]
    assert "212-555-0144" not in records[0]
    assert "My sink is clogged" not in records[0]
    assert "sink clogged" not in records[0]
    assert "resident@example.com" not in records[0]
    assert "content" not in parsed
    assert "tool_args" not in parsed
    assert parsed["route"] == "small"
    assert parsed["cache_read_tokens"] == 512
    assert len(str(parsed["org_hash"])) == 16


def test_telemetry_span_processor_redacts_pii_attributes() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://postgres:postgres@127.0.0.1:5432/pdagent_test",
        redis_url="redis://127.0.0.1:6379/0",
        environment="test",
    )
    exporter = InMemorySpanExporter()
    provider = configure_telemetry(settings, custom_exporter=exporter)
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    tracer = provider.get_tracer("pdagent.test")
    safe_attrs = sanitize_span_attributes(
        {
            "route": "small",
            "model": "claude-haiku-5-5",
            "input_tokens": 512,
            "content": "Secret tenant message",
            "phone": "+14155550199",
            "summary_note": "Email resident@example.com",
        }
    )
    with tracer.start_as_current_span("turn", attributes=safe_attrs) as span:
        span.set_attribute("user_message", "Raw message inside span")

    provider.force_flush()
    spans = exporter.get_finished_spans()
    assert len(spans) >= 1
    attrs = dict(spans[-1].attributes or {})
    assert attrs["route"] == "small"
    assert attrs["input_tokens"] == 512
    assert attrs["content"] == "[REDACTED_PII]"
    assert attrs["phone"] == "[REDACTED_PII]"
    assert "resident@example.com" not in str(attrs["summary_note"])
    assert "Secret tenant message" not in str(attrs)
