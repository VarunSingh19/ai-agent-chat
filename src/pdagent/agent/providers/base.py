"""LLMProvider protocol, model catalog loader, and 3-provider failover gateway (Architecture.md
§7f).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import yaml

from pdagent.agent.canonical import (
    CanonicalMessage,
    PromptBundle,
    RouteSlot,
    StreamEvent,
    TurnConfig,
    UsageStats,
)
from pdagent.core.errors import AppError, ErrorCode
from pdagent.limits.breaker import ProviderCircuitBreaker

logger = logging.getLogger(__name__)


class MidStreamProviderError(RuntimeError):
    """Raised when a provider fails after already emitting at least one token to the user."""


@dataclass(frozen=True, slots=True)
class ModelPricingSpec:
    """Model ID, effort level, cache threshold, and pricing loaded from config/models.yaml."""

    provider: str
    slot: str
    model_id: str
    effort: str
    min_cache_tokens: int
    input_per_1m_usd: float
    output_per_1m_usd: float
    cache_read_per_1m_usd: float
    cache_write_per_1m_usd: float
    eligible: bool

    def compute_cost_usd(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> float:
        """Compute exact USD cost for a turn (reasoning tokens bill at the output rate)."""
        uncached_in = max(0, input_tokens - cache_read_tokens - cache_write_tokens)
        total_out = output_tokens + reasoning_tokens
        cost = (
            (uncached_in / 1_000_000.0) * self.input_per_1m_usd
            + (cache_read_tokens / 1_000_000.0) * self.cache_read_per_1m_usd
            + (cache_write_tokens / 1_000_000.0) * self.cache_write_per_1m_usd
            + (total_out / 1_000_000.0) * self.output_per_1m_usd
        )
        return round(cost, 8)

    def max_reservation_usd(self, estimated_input_tokens: int, max_output_tokens: int) -> float:
        """Compute worst-case reservation USD before calling the model (Architecture.md §7e)."""
        cost = (estimated_input_tokens / 1_000_000.0) * self.input_per_1m_usd + (
            max_output_tokens / 1_000_000.0
        ) * self.output_per_1m_usd
        return round(max(cost, 0.0001), 8)


class ModelCatalog:
    """In-memory representation of `config/models.yaml` (Rules.md §4: never hardcode
    models/prices).
    """

    def __init__(self, raw: dict[str, object]) -> None:
        self.priced_on = str(raw.get("priced_on", ""))
        self._specs: dict[tuple[str, str], ModelPricingSpec] = {}
        self._failover_chains: dict[str, list[str]] = {}

        providers_raw = raw.get("providers", {})
        if isinstance(providers_raw, dict):
            for prov_name, prov_data in providers_raw.items():
                if not isinstance(prov_data, dict):
                    continue
                for slot in ("small", "large"):
                    slot_data = prov_data.get(slot)
                    if isinstance(slot_data, dict):
                        self._specs[(str(prov_name), slot)] = ModelPricingSpec(
                            provider=str(prov_name),
                            slot=slot,
                            model_id=str(slot_data["model_id"]),
                            effort=str(slot_data.get("effort", "medium")),
                            min_cache_tokens=int(slot_data.get("min_cache_tokens", 512)),
                            input_per_1m_usd=float(slot_data["input_per_1m_usd"]),
                            output_per_1m_usd=float(slot_data["output_per_1m_usd"]),
                            cache_read_per_1m_usd=float(slot_data["cache_read_per_1m_usd"]),
                            cache_write_per_1m_usd=float(slot_data["cache_write_per_1m_usd"]),
                            eligible=bool(slot_data.get("eligible", True)),
                        )

        routes_raw = raw.get("routes", {})
        if isinstance(routes_raw, dict):
            for route_name, route_data in routes_raw.items():
                if isinstance(route_data, dict):
                    chain = route_data.get("failover_chain", ["anthropic", "openai", "gemini"])
                    if isinstance(chain, list):
                        self._failover_chains[str(route_name)] = [str(c) for c in chain]

    def get_spec(self, provider: str, route: RouteSlot) -> ModelPricingSpec:
        """Return ModelPricingSpec for `(provider, route)`."""
        slot = "large" if route in ("large", "triage") else "small"
        if provider == "fake":
            base = self._specs.get(("anthropic", slot))
            if base is not None:
                return ModelPricingSpec(
                    provider="fake",
                    slot=slot,
                    model_id=base.model_id,
                    effort=base.effort,
                    min_cache_tokens=base.min_cache_tokens,
                    input_per_1m_usd=base.input_per_1m_usd,
                    output_per_1m_usd=base.output_per_1m_usd,
                    cache_read_per_1m_usd=base.cache_read_per_1m_usd,
                    cache_write_per_1m_usd=base.cache_write_per_1m_usd,
                    eligible=True,
                )
        spec = self._specs.get((provider, slot))
        if spec is None:
            msg = f"Unknown model spec for provider={provider}, slot={slot}"
            raise KeyError(msg)
        return spec

    def failover_chain(self, route: RouteSlot) -> list[str]:
        """Return ordered provider failover chain for `route`."""
        return list(self._failover_chains.get(route, ["anthropic", "openai", "gemini"]))


@lru_cache(maxsize=1)
def load_model_catalog(config_path: str = "config/models.yaml") -> ModelCatalog:
    """Load and parse `config/models.yaml`."""
    path = Path(config_path)
    if not path.exists():
        path = Path(__file__).resolve().parents[4] / "config" / "models.yaml"
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        msg = "config/models.yaml must contain a top-level mapping"
        raise ValueError(msg)
    return ModelCatalog(data)


class LLMProvider(Protocol):
    """Protocol implemented by Anthropic, OpenAI, Google Gemini, and Fake providers."""

    @property
    def name(self) -> str:
        """Provider identifier (`anthropic`, `openai`, `gemini`, `fake`)."""

    def stream(
        self,
        prompt: PromptBundle,
        messages: list[CanonicalMessage],
        config: TurnConfig,
        model_spec: ModelPricingSpec,
    ) -> AsyncIterator[StreamEvent]:
        """Yield canonical `StreamEvent` items for the turn."""


class ProviderGateway:
    """Executes model calls with 1 retry per provider and 3-way failover (Anthropic ▸ OpenAI ▸ G

    Per Architecture.md §7f:
    - Retries once on provider failure before the first token is emitted.
    - Fails over across eligible providers ONLY before the first token reaches the user.
    - If a failure occurs AFTER the first token has been yielded, raises `MidStreamProviderError`
      so the caller emits an `error` event and never splices responses from two providers.
    """

    def __init__(
        self,
        providers: dict[str, LLMProvider],
        *,
        catalog: ModelCatalog | None = None,
        breaker: ProviderCircuitBreaker | None = None,
        max_retries_per_provider: int = 1,
    ) -> None:
        self._providers = providers
        self.catalog = catalog or load_model_catalog()
        self.breaker = breaker or ProviderCircuitBreaker()
        self.max_retries_per_provider = max_retries_per_provider

    async def stream_with_failover(
        self,
        prompt: PromptBundle,
        messages: list[CanonicalMessage],
        config: TurnConfig,
    ) -> AsyncIterator[StreamEvent]:
        """Stream events from the primary provider or fail over cleanly if pre-first-token."""
        chain = [p for p in self.catalog.failover_chain(config.route) if p in self._providers]
        if not chain and "fake" in self._providers:
            chain = ["fake"]

        primary_provider = chain[0] if chain else ""
        last_error: Exception | None = None

        for provider_name in chain:
            if not self.breaker.allow_request(provider_name):
                logger.warning(
                    "Skipping provider due to open circuit breaker",
                    extra={"provider": provider_name},
                )
                continue

            provider = self._providers[provider_name]
            spec = self.catalog.get_spec(provider_name, config.route)
            if not spec.eligible:
                continue

            is_failover = provider_name != primary_provider

            for _attempt in range(self.max_retries_per_provider + 1):
                emitted_token = False
                try:
                    async for event in provider.stream(prompt, messages, config, spec):
                        if event.kind == "token" and event.text:
                            emitted_token = True
                        if event.kind == "usage" and event.usage is not None:
                            cost = spec.compute_cost_usd(
                                input_tokens=event.usage.input_tokens,
                                output_tokens=event.usage.output_tokens,
                                cache_read_tokens=event.usage.cache_read_tokens,
                                cache_write_tokens=event.usage.cache_write_tokens,
                                reasoning_tokens=event.usage.reasoning_tokens,
                            )
                            enriched = UsageStats(
                                provider=provider_name,
                                model=spec.model_id,
                                input_tokens=event.usage.input_tokens,
                                output_tokens=event.usage.output_tokens,
                                cache_read_tokens=event.usage.cache_read_tokens,
                                cache_write_tokens=event.usage.cache_write_tokens,
                                reasoning_tokens=event.usage.reasoning_tokens,
                                cost_usd=cost,
                                failover=is_failover,
                            )
                            yield StreamEvent(kind="usage", usage=enriched)
                        else:
                            yield event
                    self.breaker.record_success(provider_name)
                    return
                except Exception as exc:
                    last_error = exc
                    self.breaker.record_failure(provider_name)
                    if emitted_token:
                        logger.error(
                            "Provider failed after emitting tokens; aborting without splicing",
                            extra={"provider": provider_name},
                        )
                        raise MidStreamProviderError(
                            "Stream interrupted after first token"
                        ) from exc
                    logger.warning(
                        "Provider attempt failed before first token",
                        extra={"provider": provider_name},
                    )

        raise AppError(
            code=ErrorCode.PROVIDER_UNAVAILABLE,
            title="AI Providers Unavailable",
            detail="All configured model providers are temporarily unavailable.",
            status_code=503,
        ) from last_error
