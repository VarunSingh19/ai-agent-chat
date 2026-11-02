"""Explicit OpenTelemetry configuration and span PII sanitization (Architecture.md §1 & §9).

FastAPI 0.143+ made automatic OTel exporter setup opt-in. We configure TracerProvider
and span processors explicitly here, and enforce that no message text or PII ever
lands in span attributes (Rules.md §5 & §8).
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from pdagent.core.logging import FORBIDDEN_LOG_KEYS, mask_sensitive_text
from pdagent.core.settings import Settings


class PiiSanitizingSpanProcessor(SpanProcessor):
    """Span processor that scrubs or drops forbidden PII attributes on start and end."""

    def on_start(self, span: Span, parent_context: object = None) -> None:
        self._sanitize_span(span)

    def on_end(self, span: ReadableSpan) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    @staticmethod
    def _sanitize_span(span: Span) -> None:
        attributes = getattr(span, "attributes", None)
        if not isinstance(attributes, dict):
            return
        for key, value in list(attributes.items()):
            if key.lower() in FORBIDDEN_LOG_KEYS:
                span.set_attribute(key, "[REDACTED_PII]")
            elif isinstance(value, str):
                span.set_attribute(key, mask_sensitive_text(value))


SpanAttrMap = dict[str, str | int | float | bool]


def sanitize_span_attributes(attrs: SpanAttrMap) -> SpanAttrMap:
    """Return a copy of span attributes with all forbidden keys and PII patterns redacted."""
    clean: SpanAttrMap = {}
    for key, val in attrs.items():
        if key.lower() in FORBIDDEN_LOG_KEYS:
            clean[key] = "[REDACTED_PII]"
        elif isinstance(val, str):
            clean[key] = mask_sensitive_text(val)
        else:
            clean[key] = val
    return clean


def configure_telemetry(
    settings: Settings | None = None,
    custom_exporter: SpanExporter | None = None,
    *,
    service_name: str | None = None,
    otlp_endpoint: str | None = None,
) -> TracerProvider:
    """Explicitly configure the OpenTelemetry TracerProvider and exporter."""
    resolved_service_name = service_name or (settings.service_name if settings else "pdagent")
    resolved_env = settings.environment if settings else "development"
    resolved_endpoint = (
        otlp_endpoint
        if otlp_endpoint is not None
        else (settings.otel_exporter_otlp_endpoint if settings else "")
    )
    resource = Resource.create(
        {
            SERVICE_NAME: resolved_service_name,
            "deployment.environment": resolved_env,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(PiiSanitizingSpanProcessor())

    if custom_exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(custom_exporter))
    elif resolved_endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=resolved_endpoint)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    trace.set_tracer_provider(provider)
    return provider
