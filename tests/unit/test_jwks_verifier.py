"""Unit tests for JWKS-backed token verification and verifier fail-fast wiring (Phase 1)."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Literal
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from pdagent.auth.token import (
    JwksKeySource,
    TokenVerifier,
    build_token_verifier,
    mint_test_token,
)
from pdagent.core.errors import AppError
from pdagent.core.settings import Settings

ISSUER = "https://issuer.test"
KID = "test-kid-1"


def _settings(
    *, environment: Literal["development", "test", "staging", "production"], jwks_url: str
) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://app:pw@localhost:5432/pdagent",
        redis_url="redis://localhost:6379/0",
        token_issuer=ISSUER,
        environment=environment,
        jwks_url=jwks_url,
    )


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks_server(signing_key: rsa.RSAPrivateKey) -> Iterator[tuple[str, list[int]]]:
    """Serve a one-key JWKS on localhost; yields (url, request counter)."""
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    body = json.dumps({"keys": [{**jwk, "kid": KID, "alg": "RS256", "use": "sig"}]}).encode()
    hits = [0]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            hits[0] += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/jwks.json", hits
    server.shutdown()


def _token(key: rsa.RSAPrivateKey, *, kid: str = KID, issuer: str = ISSUER) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid4()),
        "org_id": str(uuid4()),
        "role": "tenant",
        "property_ids": [],
        "jti": str(uuid4()),
        "iss": issuer,
        "aud": "pdagent",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
    }
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return jwt.encode(payload, pem, algorithm="RS256", headers={"kid": kid})


async def test_jwks_verifier_accepts_token_signed_by_published_key(
    signing_key: rsa.RSAPrivateKey, jwks_server: tuple[str, list[int]]
) -> None:
    url, _ = jwks_server
    verifier = TokenVerifier(issuer=ISSUER, audience="pdagent", jwks=JwksKeySource(url))
    principal = await verifier.verify_token(_token(signing_key))
    assert principal.role == "tenant"


async def test_jwks_verifier_rejects_unknown_kid_and_throttles_refetch(
    signing_key: rsa.RSAPrivateKey, jwks_server: tuple[str, list[int]]
) -> None:
    url, hits = jwks_server
    source = JwksKeySource(url, min_refresh_interval_s=3600)
    verifier = TokenVerifier(issuer=ISSUER, audience="pdagent", jwks=source)
    before = hits[0]
    for _ in range(3):
        with pytest.raises(AppError) as exc_info:
            await verifier.verify_token(_token(signing_key, kid="forged-kid"))
        assert exc_info.value.status_code == 401
    # One initial fetch plus at most one forced refresh, however many forged kids arrive.
    assert hits[0] - before <= 2


async def test_jwks_verifier_rejects_token_from_other_key(
    jwks_server: tuple[str, list[int]],
) -> None:
    url, _ = jwks_server
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = TokenVerifier(issuer=ISSUER, audience="pdagent", jwks=JwksKeySource(url))
    with pytest.raises(AppError) as exc_info:
        await verifier.verify_token(_token(other_key))
    assert exc_info.value.status_code == 401


async def test_jwks_verifier_rejects_in_process_test_key() -> None:
    """Outside the test environment, tokens from `mint_test_token` must not verify."""
    verifier = build_token_verifier(
        _settings(environment="development", jwks_url="http://127.0.0.1:9/jwks.json")
    )
    token = mint_test_token(org_id=uuid4(), user_id=uuid4(), issuer=ISSUER)
    with pytest.raises(AppError):
        await verifier.verify_token(token)


def test_build_token_verifier_fails_fast_on_missing_or_insecure_jwks_url() -> None:
    with pytest.raises(RuntimeError, match="PDAGENT_JWKS_URL must be set"):
        build_token_verifier(_settings(environment="production", jwks_url=""))
    with pytest.raises(RuntimeError, match="https"):
        build_token_verifier(
            _settings(environment="production", jwks_url="http://auth.example.com/jwks.json")
        )
    assert isinstance(
        build_token_verifier(
            _settings(environment="development", jwks_url="http://127.0.0.1:5173/dev/jwks.json")
        ),
        TokenVerifier,
    )
