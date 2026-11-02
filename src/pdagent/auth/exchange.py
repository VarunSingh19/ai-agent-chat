"""RFC 8693 OAuth 2.0 Token Exchange for MCP -> PropertyDek calls (Architecture.md §6.6, D-017)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from pdagent.auth.principal import Principal
from pdagent.auth.token import TEST_PRIVATE_KEY_PEM
from pdagent.core.ids import new_id


def exchange_token_for_pdapi(
    principal: Principal,
    *,
    issuer: str = "pdagent-token-exchange",
    private_key_pem: str = TEST_PRIVATE_KEY_PEM,
    ttl_seconds: int = 60,
) -> str:
    """Exchange a verified `aud="pdagent"` Principal for a short-lived `aud="pdapi"` token.

    Per MCP specification 2026-07-28 and Architecture.md §6.6 (Decision D-017),
    the MCP server MUST NOT pass through upstream client tokens directly. Instead,
    it issues a narrowly scoped, audience-bound (`aud="pdapi"`) token carrying only
    the user's verified Principal scope.
    """
    if principal.raw_token and _is_already_pdapi_audience(principal.raw_token):
        msg = "Token passthrough is forbidden; input token must target pdagent"
        raise ValueError(msg)

    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(principal.user_id),
        "org_id": str(principal.org_id),
        "role": principal.role,
        "property_ids": [str(pid) for pid in principal.property_ids],
        "unit_id": str(principal.unit_id) if principal.unit_id else None,
        "jti": str(new_id()),
        "act": {"sub": "pdagent-mcp-server"},
        "iss": issuer,
        "aud": "pdapi",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def _is_already_pdapi_audience(raw_token: str) -> bool:
    try:
        unverified = jwt.decode(raw_token, options={"verify_signature": False})
        return unverified.get("aud") == "pdapi"
    except Exception:
        return False
