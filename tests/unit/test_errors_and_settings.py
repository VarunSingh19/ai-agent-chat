"""Unit tests for Settings fail-fast, UUIDv7 helpers, and RFC 9457 error handling."""

from __future__ import annotations

import uuid
from datetime import UTC

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from pdagent.core.db import normalize_async_db_url
from pdagent.core.errors import AppError, ErrorCode, register_exception_handlers
from pdagent.core.ids import extract_uuid7_timestamp, new_uuid7, new_uuid7_str, utc_now
from pdagent.core.settings import Settings


class SampleValidationPayload(BaseModel):
    """Module-level Pydantic model so FastAPI resolves string annotations under PEP 563."""

    count: int
    secret_phone: str


def test_settings_fails_fast_on_blank_urls() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="   ", redis_url="redis://localhost:6379/0")

    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+psycopg://app:pw@localhost:5432/pdagent",
            redis_url="",
        )


def test_normalize_async_db_url_enforces_psycopg3() -> None:
    assert (
        normalize_async_db_url("postgresql://u:p@localhost:5432/db")
        == "postgresql+psycopg://u:p@localhost:5432/db"
    )
    assert (
        normalize_async_db_url("postgres://u:p@localhost:5432/db")
        == "postgresql+psycopg://u:p@localhost:5432/db"
    )
    assert (
        normalize_async_db_url("postgresql+psycopg://u:p@localhost:5432/db")
        == "postgresql+psycopg://u:p@localhost:5432/db"
    )
    with pytest.raises(ValueError, match="forbidden"):
        normalize_async_db_url("postgresql+psycopg2://u:p@localhost:5432/db")
    with pytest.raises(ValueError, match="forbidden"):
        normalize_async_db_url("postgresql+asyncpg://u:p@localhost:5432/db")


def test_uuid7_generation_and_utc_timestamp_extraction() -> None:
    before = utc_now()
    uid = new_uuid7()
    uid_str = new_uuid7_str()
    after = utc_now()

    assert uid.version == 7
    assert len(uid_str) == 36
    extracted = extract_uuid7_timestamp(uid)
    assert extracted.tzinfo == UTC
    assert (before.timestamp() - 1.0) <= extracted.timestamp() <= (after.timestamp() + 1.0)

    with pytest.raises(ValueError, match="Expected UUIDv7"):
        extract_uuid7_timestamp(uuid.uuid4())


def test_problem_json_error_handlers_never_echo_pii_or_stack_traces() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/validate-test")
    async def validate_endpoint(body: SampleValidationPayload) -> dict[str, int]:
        return {"count": body.count}

    @app.get("/app-error-test")
    async def app_error_endpoint() -> None:
        raise AppError(
            status=429,
            code=ErrorCode.RATE_LIMITED,
            title="Rate Limited",
            detail="Rate limit exceeded.",
            headers={"Retry-After": "30"},
        )

    @app.get("/auth-error-test")
    async def auth_error_endpoint() -> None:
        raise AppError(
            status=401,
            code=ErrorCode.AUTH_INVALID_TOKEN,
            title="Invalid Token",
            detail="Authentication token is invalid or expired.",
        )

    @app.get("/crash-test")
    async def crash_endpoint() -> None:
        msg = "Database failed for tenant secret.user@example.com with phone 415-555-0199"
        raise RuntimeError(msg)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        # 1. 422 Validation error must include field path but NEVER echo the sensitive input value
        res_422 = test_client.post(
            "/validate-test",
            json={"count": "not-an-int-for-415-555-0199", "secret_phone": "+14155550199"},
        )
        assert res_422.status_code == 422
        assert res_422.headers["content-type"].startswith("application/problem+json")
        body_422 = res_422.json()
        assert body_422["code"] == "VALIDATION"
        assert "body.count" in body_422["fields"]
        assert "415-555-0199" not in res_422.text
        assert "not-an-int" not in res_422.text

        # 2. 429 AppError includes Retry-After header and problem+json shape
        res_429 = test_client.get("/app-error-test")
        assert res_429.status_code == 429
        assert res_429.headers["Retry-After"] == "30"
        assert res_429.json()["code"] == "RATE_LIMITED"

        # 3. 401 AUTH_INVALID_TOKEN logs warning and returns problem+json
        res_401 = test_client.get("/auth-error-test")
        assert res_401.status_code == 401
        assert res_401.json()["code"] == "AUTH_INVALID_TOKEN"

        # 4. 500 Unhandled exception returns request_id and code INTERNAL, never leaking text
        res_500 = test_client.get("/crash-test")
        assert res_500.status_code == 500
        body_500 = res_500.json()
        assert body_500["code"] == "INTERNAL"
        assert body_500["request_id"]
        assert "secret.user@example.com" not in res_500.text
        assert "415-555-0199" not in res_500.text
        assert "RuntimeError" not in res_500.text
