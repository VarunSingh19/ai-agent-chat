"""JWT verification, JWKS key handling, and test token minting (Phase 1, Rules.md §3)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from pdagent.auth.principal import Principal, Role
from pdagent.core.errors import AppError, ErrorCode
from pdagent.core.ids import new_id

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from pdagent.core.settings import Settings

logger = logging.getLogger(__name__)

VALID_ROLES: frozenset[str] = frozenset({"tenant", "pm_member", "org_admin", "fbc_operator"})

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PRIVATE_KEY_PEM: str = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")
TEST_PUBLIC_KEY_PEM: str = (
    _PRIVATE_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode("utf-8")
)


def mint_test_token(
    *,
    org_id: UUID,
    user_id: UUID,
    role: Role = "tenant",
    property_ids: list[UUID] | tuple[UUID, ...] = (),
    unit_id: UUID | None = None,
    jti: str | None = None,
    issuer: str = "https://auth.propertydek.example.com",
    audience: str = "pdagent",
    expires_delta: timedelta = timedelta(minutes=15),
    private_key_pem: str = TEST_PRIVATE_KEY_PEM,
) -> str:
    """Mint an RS256-signed JWT for unit and integration tests."""
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "property_ids": [str(pid) for pid in property_ids],
        "unit_id": str(unit_id) if unit_id is not None else None,
        "jti": jti or str(new_id()),
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


class JwksKeySource:
    """Signing keys from PropertyDek's JWKS (Architecture.md §6.2).

    The key set is cached; an unknown `kid` triggers a refetch at most once per
    `min_refresh_interval_s`, so forged `kid` values cannot hammer the JWKS endpoint.
    Fetches run in a worker thread (PyJWKClient uses blocking urllib).
    """

    def __init__(
        self,
        jwks_url: str,
        *,
        cache_lifespan_s: int = 300,
        min_refresh_interval_s: float = 30.0,
        timeout_s: int = 5,
    ) -> None:
        self._client = jwt.PyJWKClient(
            jwks_url, cache_jwk_set=True, lifespan=cache_lifespan_s, timeout=timeout_s
        )
        self._min_refresh_interval_s = min_refresh_interval_s
        self._last_forced_refresh = float("-inf")
        self._refresh_lock = asyncio.Lock()

    async def signing_key(self, raw_token: str) -> jwt.PyJWK:
        """Return the public key for the token's `kid`; raise a `PyJWTError` if none matches."""
        kid = jwt.get_unverified_header(raw_token).get("kid")
        if not isinstance(kid, str) or not kid:
            raise jwt.InvalidTokenError("Token header has no kid")
        jwk_set = await asyncio.to_thread(self._client.get_jwk_set)
        key = _find_key(jwk_set, kid)
        if key is None:
            async with self._refresh_lock:
                now = time.monotonic()
                if now - self._last_forced_refresh >= self._min_refresh_interval_s:
                    self._last_forced_refresh = now
                    jwk_set = await asyncio.to_thread(self._client.get_jwk_set, True)
                    key = _find_key(jwk_set, kid)
        if key is None:
            raise jwt.InvalidTokenError("No JWKS key matches the token kid")
        return key


def _find_key(jwk_set: jwt.PyJWKSet, kid: str) -> jwt.PyJWK | None:
    for jwk in jwk_set.keys:
        if jwk.key_id == kid:
            return jwk
    return None


class TokenVerifier:
    """Verifies RS256/ES256 JWTs and checks Redis JTI revocation list.

    Keys come from `jwks` when given; otherwise from `public_key_pem` (the in-process
    test key by default, used only by the test environment and test helpers).
    """

    def __init__(
        self,
        *,
        issuer: str = "https://auth.propertydek.example.com",
        audience: str = "pdagent",
        public_key_pem: str = TEST_PUBLIC_KEY_PEM,
        jwks: JwksKeySource | None = None,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._public_key_pem = public_key_pem
        self._jwks = jwks

    async def verify_token(self, raw_token: str, redis_client: Redis | None = None) -> Principal:
        """Verify JWT signature, claims, expiry, audience, and revocation status."""
        cleaned = raw_token.strip()
        if not cleaned:
            raise AppError(
                code=ErrorCode.AUTH_INVALID_TOKEN,
                title="Authentication Required",
                detail="Missing bearer token.",
                status_code=401,
            )

        try:
            key: jwt.PyJWK | str = (
                await self._jwks.signing_key(cleaned)
                if self._jwks is not None
                else self._public_key_pem
            )
            decoded: dict[str, object] = jwt.decode(
                cleaned,
                key,
                algorithms=["RS256", "ES256"],
                audience=self._audience,
                issuer=self._issuer if self._issuer else None,
                options={
                    "require": ["exp", "sub", "org_id", "role", "jti", "aud"],
                },
            )
        except jwt.PyJWTError as exc:
            logger.warning("JWT verification failed", extra={"reason": type(exc).__name__})
            raise AppError(
                code=ErrorCode.AUTH_INVALID_TOKEN,
                title="Invalid Authentication Token",
                detail="The provided authentication token is invalid or expired.",
                status_code=401,
            ) from exc

        jti = str(decoded.get("jti", "")).strip()
        if not jti:
            raise AppError(
                code=ErrorCode.AUTH_INVALID_TOKEN,
                title="Invalid Authentication Token",
                detail="Token is missing required jti claim.",
                status_code=401,
            )

        revoked = jti in _REVOKED_JTIS
        if not revoked and redis_client is not None:
            try:
                redis_revoked = await redis_client.get(f"revoked:jti:{jti}")
                revoked = redis_revoked is not None
            except Exception:
                revoked = False
        if revoked:
            logger.warning("Revoked JWT presented", extra={"jti": jti})
            raise AppError(
                code=ErrorCode.AUTH_INVALID_TOKEN,
                title="Revoked Authentication Token",
                detail="The authentication token has been revoked.",
                status_code=401,
            )

        role_raw = str(decoded.get("role", ""))
        if role_raw not in VALID_ROLES:
            raise AppError(
                code=ErrorCode.AUTH_INVALID_TOKEN,
                title="Invalid Role Claim",
                detail="Token role claim is not recognized.",
                status_code=401,
            )

        try:
            org_id = UUID(str(decoded["org_id"]))
            user_id = UUID(str(decoded["sub"]))
            raw_props = decoded.get("property_ids") or []
            if not isinstance(raw_props, list):
                raise ValueError("property_ids must be a list")
            property_ids = tuple(UUID(str(p)) for p in raw_props)
            raw_unit = decoded.get("unit_id")
            unit_id = UUID(str(raw_unit)) if raw_unit else None
        except (ValueError, KeyError, TypeError) as exc:
            raise AppError(
                code=ErrorCode.AUTH_INVALID_TOKEN,
                title="Malformed Identity Claims",
                detail="Token identity claims are malformed.",
                status_code=401,
            ) from exc

        return Principal(
            org_id=org_id,
            user_id=user_id,
            role=cast(Role, role_raw),
            property_ids=property_ids,
            unit_id=unit_id,
            jti=jti,
            raw_token=cleaned,
        )


_REVOKED_JTIS: set[str] = set()


async def revoke_token_jti(redis_client: Redis | None, jti: str, ttl_seconds: int = 3600) -> None:
    """Add a JWT `jti` to the Redis revocation list and local revocation cache."""
    _REVOKED_JTIS.add(jti)
    if redis_client is not None:
        try:
            await redis_client.setex(f"revoked:jti:{jti}", ttl_seconds, "1")
        except Exception:
            logger.debug("Redis JTI setex skipped; stored in process revocation set")


def build_token_verifier(settings: Settings) -> TokenVerifier:
    """Build the app's verifier: JWKS everywhere except the test environment.

    Fails fast at startup when `PDAGENT_JWKS_URL` is blank, or is not HTTPS outside
    development (Rules.md §7: startup fails with a clear message on bad config).
    """
    if settings.environment == "test":
        return TokenVerifier(issuer=settings.token_issuer, audience=settings.token_audience)
    jwks_url = settings.jwks_url.strip()
    if not jwks_url:
        msg = "PDAGENT_JWKS_URL must be set outside the test environment"
        raise RuntimeError(msg)
    if settings.environment != "development" and not jwks_url.startswith("https://"):
        msg = "PDAGENT_JWKS_URL must use https:// outside development"
        raise RuntimeError(msg)
    return TokenVerifier(
        issuer=settings.token_issuer,
        audience=settings.token_audience,
        jwks=JwksKeySource(jwks_url),
    )
