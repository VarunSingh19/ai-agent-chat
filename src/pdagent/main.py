"""FastAPI application entrypoint, lifespan, readiness, and router mounting (Architecture.md §3,
§8).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from pdagent.agent.providers.anthropic import AnthropicProvider
from pdagent.agent.providers.base import LLMProvider, ProviderGateway, load_model_catalog
from pdagent.agent.providers.fake import FakeLLMProvider
from pdagent.agent.providers.gemini import GeminiProvider
from pdagent.agent.providers.openai import OpenAIProvider
from pdagent.auth.token import build_token_verifier
from pdagent.channels.sms.adapter import SmsChannelAdapter
from pdagent.channels.sms.webhook import router as sms_router
from pdagent.conversations.router import router as conversations_router
from pdagent.core.db import check_db_ready, create_db_engine, create_session_factory
from pdagent.core.errors import AppError, ErrorCode, problem_response, register_error_handlers
from pdagent.core.ids import new_id
from pdagent.core.logging import configure_logging
from pdagent.core.settings import Settings, get_settings
from pdagent.core.telemetry import configure_telemetry
from pdagent.handoff.notify import StaffAlertDispatcher
from pdagent.handoff.router import router as handoff_router
from pdagent.inbox.router import router as inbox_router
from pdagent.inbox.ws import router as inbox_ws_router
from pdagent.knowledge.ingest.embed import EmbeddingClient
from pdagent.knowledge.router import router as knowledge_router
from pdagent.limits.breaker import ProviderCircuitBreaker
from pdagent.limits.ratelimit import SlidingWindowRateLimiter
from pdagent.limits.spend import SpendGuard
from pdagent.mcp_server.pdapi_client import PropertyDekApiClient
from pdagent.mcp_server.server import StatelessMcpGateway
from pdagent.settings_org.router import router as settings_org_router
from pdagent.tools.confirm import router as confirmations_router

logger = logging.getLogger(__name__)


async def check_redis_ready(redis_client: Redis | None, timeout_s: float = 2.0) -> bool:
    """Ping Redis directly for `/readyz`."""
    if redis_client is None:
        return False
    try:
        async with asyncio.timeout(timeout_s):
            pong = await redis_client.ping()  # type: ignore[misc]
            return bool(pong)
    except Exception:
        logger.warning("Redis readiness check failed")
        return False


def build_default_provider_gateway(settings: Settings) -> ProviderGateway:
    """Build the 3-provider gateway (`anthropic` ▸ `openai` ▸ `gemini`) or Fake fallback."""
    providers: dict[str, LLMProvider] = {}
    if settings.anthropic_api_key:
        providers["anthropic"] = AnthropicProvider(api_key=settings.anthropic_api_key)
    else:
        providers["anthropic"] = FakeLLMProvider(provider_name="anthropic")

    if settings.openai_api_key:
        providers["openai"] = OpenAIProvider(api_key=settings.openai_api_key)
    else:
        providers["openai"] = FakeLLMProvider(provider_name="openai")

    if settings.gemini_api_key:
        providers["gemini"] = GeminiProvider(api_key=settings.gemini_api_key)
    else:
        providers["gemini"] = FakeLLMProvider(provider_name="gemini")

    providers["fake"] = FakeLLMProvider(provider_name="fake")
    return ProviderGateway(
        providers=providers,
        catalog=load_model_catalog(),
        breaker=ProviderCircuitBreaker(),
    )


def create_app(
    settings: Settings | None = None,
    *,
    db_check_override: Callable[[], Awaitable[bool]] | None = None,
    redis_check_override: Callable[[], Awaitable[bool]] | None = None,
    redis_client_override: Any | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance across Phases 0-11."""
    configure_logging()
    resolved_settings = settings or get_settings()
    configure_telemetry(
        service_name=resolved_settings.service_name,
        otlp_endpoint=resolved_settings.otel_exporter_otlp_endpoint,
    )

    token_verifier = build_token_verifier(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_db_engine(resolved_settings)
        session_factory = create_session_factory(engine)
        redis_client: Any = (
            redis_client_override
            if redis_client_override is not None
            else Redis.from_url(resolved_settings.redis_url, decode_responses=True)
        )

        app.state.settings = resolved_settings
        app.state.db_engine = engine
        app.state.session_factory = session_factory
        app.state.redis_client = redis_client
        app.state.token_verifier = token_verifier
        app.state.rate_limiter = SlidingWindowRateLimiter(
            redis_client if redis_client_override is None else None
        )
        app.state.spend_guard = SpendGuard(
            redis_client if redis_client_override is None else None,
            global_daily_cap_usd=resolved_settings.global_daily_cap_usd,
            default_user_daily_cap_usd=resolved_settings.user_daily_cap_usd,
        )
        app.state.pdapi_client = PropertyDekApiClient()
        app.state.mcp_gateway = StatelessMcpGateway(app.state.pdapi_client)
        app.state.staff_notifier = StaffAlertDispatcher()
        app.state.provider_gateway = build_default_provider_gateway(resolved_settings)
        app.state.embedder = EmbeddingClient()
        app.state.sms_adapter = SmsChannelAdapter(
            webhook_secret=resolved_settings.sms_webhook_secret
        )

        logger.info(
            "pdagent startup complete", extra={"environment": resolved_settings.environment}
        )
        try:
            yield
        finally:
            try:
                await redis_client.aclose()
            except RuntimeError:
                logger.debug("Redis client aclose skipped across event loops")
            await engine.dispose()
            logger.info("pdagent shutdown complete")

    app = FastAPI(
        title="PropertyDek AI Assistant (pdagent)",
        version="0.1.0",
        docs_url=None if resolved_settings.environment == "production" else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.db_engine = None
    app.state.session_factory = None
    app.state.redis_client = redis_client_override
    app.state.token_verifier = token_verifier
    app.state.rate_limiter = SlidingWindowRateLimiter(None)
    app.state.spend_guard = SpendGuard(
        None,
        global_daily_cap_usd=resolved_settings.global_daily_cap_usd,
        default_user_daily_cap_usd=resolved_settings.user_daily_cap_usd,
    )
    app.state.pdapi_client = PropertyDekApiClient()
    app.state.mcp_gateway = StatelessMcpGateway(app.state.pdapi_client)
    app.state.staff_notifier = StaffAlertDispatcher()
    app.state.provider_gateway = build_default_provider_gateway(resolved_settings)
    app.state.embedder = EmbeddingClient()
    app.state.sms_adapter = SmsChannelAdapter(webhook_secret=resolved_settings.sms_webhook_secret)

    register_error_handlers(app)

    @app.middleware("http")
    async def attach_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        inbound_id = request.headers.get("X-Request-ID", "").strip()
        req_id = inbound_id if (inbound_id and len(inbound_id) <= 64) else str(new_id())
        request.state.request_id = req_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        """Liveness probe — always returns 200 if the process is alive (Rules.md §1 Rule 6)."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz(request: Request) -> JSONResponse:
        """Readiness probe checking PostgreSQL and Redis (Rules.md §7)."""
        timeout_s = resolved_settings.readiness_timeout_s

        if db_check_override is not None:
            db_ok = await db_check_override()
        else:
            engine: Any = getattr(request.app.state, "db_engine", None)
            db_ok = await check_db_ready(engine, timeout_s=timeout_s) if engine else False

        if redis_check_override is not None:
            redis_ok = await redis_check_override()
        else:
            redis_client: Redis | None = getattr(request.app.state, "redis_client", None)
            redis_ok = await check_redis_ready(redis_client, timeout_s=timeout_s)

        checks = {
            "db": "ok" if db_ok else "down",
            "redis": "ok" if redis_ok else "down",
        }
        if db_ok and redis_ok:
            return JSONResponse(status_code=200, content={"status": "ready", "checks": checks})

        err = AppError(
            code=ErrorCode.PROVIDER_UNAVAILABLE,
            title="Service Not Ready",
            detail="One or more backing stores failed the readiness check.",
            status_code=503,
            extra_fields={"checks": checks},
        )
        req_id = str(getattr(request.state, "request_id", new_id()))
        return problem_response(err, request_id=req_id)

    # Mount all Phase 2-10 feature routers
    app.include_router(conversations_router)
    app.include_router(confirmations_router)
    app.include_router(handoff_router)
    app.include_router(inbox_router)
    app.include_router(inbox_ws_router)
    app.include_router(knowledge_router)
    app.include_router(settings_org_router)
    app.include_router(sms_router)

    return app
