"""Phase 1 & Cross-Phase Two-Org Isolation, JWT Security, Audit Append-Only, and 100-Parallel Spend
Tests.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.testclient import TestClient

from pdagent.auth.principal import Principal
from pdagent.auth.token import mint_test_token, revoke_token_jti
from pdagent.core.db import create_session_factory
from pdagent.core.ids import new_id
from pdagent.core.rls import tenant_transaction
from pdagent.core.settings import Settings
from pdagent.limits.spend import SpendGuard
from pdagent.main import create_app

EXPECTED_OPENAPI_PATHS: frozenset[str] = frozenset(
    {
        "/healthz",
        "/readyz",
        "/v1/conversations",
        "/v1/conversations/{conversation_id}/messages",
        "/v1/conversations/{conversation_id}/handoff",
        "/v1/confirmations/{confirmation_id}/confirm",
        "/v1/confirmations/{confirmation_id}/cancel",
        "/v1/inbox/conversations",
        "/v1/inbox/conversations/{conversation_id}",
        "/v1/inbox/conversations/{conversation_id}/take",
        "/v1/inbox/conversations/{conversation_id}/release",
        "/v1/inbox/conversations/{conversation_id}/messages",
        "/v1/knowledge/documents",
        "/v1/knowledge/documents/{document_id}",
        "/v1/knowledge/documents/{document_id}/replace",
        "/v1/settings/agent",
        "/v1/admin/usage",
        "/v1/channels/sms/inbound",
        "/v1/channels/sms/status",
    }
)


def _apply_migrations(database_url: str) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def test_every_openapi_route_is_registered_in_isolation_suite(test_settings: Settings) -> None:
    """Rules.md §5 LLM02: Adding a route without registering it in the isolation suite fails CI."""
    app = create_app(test_settings)
    schema = app.openapi()
    actual_paths = set(schema.get("paths", {}).keys())
    unregistered = actual_paths - EXPECTED_OPENAPI_PATHS
    assert not unregistered, f"Routes missing from isolation suite: {unregistered}"


async def test_jwt_forged_expired_wrong_audience_and_revoked_return_401(
    test_settings: Settings,
) -> None:
    """Phases.md Phase 1 exit criterion: forged, expired, wrong-audience, and revoked tokens return
    401.
    """
    app = create_app(test_settings)
    org_id = new_id()
    user_id = new_id()

    expired_tok = mint_test_token(
        org_id=org_id,
        user_id=user_id,
        expires_delta=timedelta(minutes=-5),
    )
    wrong_aud_tok = mint_test_token(
        org_id=org_id,
        user_id=user_id,
        audience="pdapi",
    )
    forged_tok = expired_tok[:-6] + "abcdef"

    with TestClient(app) as client:
        for bad_tok in (expired_tok, wrong_aud_tok, forged_tok):
            resp = client.post(
                "/v1/conversations",
                headers={"Authorization": f"Bearer {bad_tok}"},
            )
            assert resp.status_code == 401
            assert resp.json()["code"] == "AUTH_INVALID_TOKEN"

        # Revoked token check via Redis
        revoked_jti = str(new_id())
        valid_tok = mint_test_token(org_id=org_id, user_id=user_id, jti=revoked_jti)
        await revoke_token_jti(app.state.redis_client, revoked_jti)
        rev_resp = client.post(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {valid_tok}"},
        )
        assert rev_resp.status_code == 401
        assert rev_resp.json()["code"] == "AUTH_INVALID_TOKEN"


async def test_100_parallel_spend_reservations_never_exceed_cap() -> None:
    """Phases.md Phase 1 exit criterion: 100 parallel spend
    reservations never exceed a small cap."""
    guard = SpendGuard(
        None,
        default_org_daily_cap_usd=1.00,
        default_user_daily_cap_usd=1.00,
        global_daily_cap_usd=10.00,
    )
    org_id = new_id()
    user_id = new_id()

    # 100 parallel calls each requesting $0.05 against a $1.00 cap -> exactly 20 may succeed
    results = await asyncio.gather(
        *[guard.reserve(org_id=org_id, user_id=user_id, max_cost_usd=0.05) for _ in range(100)]
    )
    allowed_count = sum(1 for r in results if r.allowed)
    assert allowed_count == 20
    spent_today = await guard.get_org_spend_today(org_id)
    assert spent_today <= 1.000001


async def test_audit_log_is_append_only_for_pdagent_app_role(
    db_engine: AsyncEngine,
    postgres_url: str,
) -> None:
    """Phases.md Phase 1 exit criterion: the app DB role cannot UPDATE or DELETE audit_log."""
    _apply_migrations(postgres_url)
    session_factory = create_session_factory(db_engine)
    org_id = new_id()
    user_id = new_id()

    async with session_factory() as session, tenant_transaction(session, org_id):
        from pdagent.audit.service import AuditService

        principal = Principal(
            org_id=org_id,
            user_id=user_id,
            role="org_admin",
            property_ids=(),
            unit_id=None,
            jti="jti-1",
            raw_token="",
        )
        row = await AuditService.record(
            session,
            principal=principal,
            action="test.action",
            target_type="test",
            target_id="1",
            outcome="ok",
        )

    # Verify table privileges in information_schema: pdagent_app has SELECT & INSERT, NOT UPDATE or
    # DELETE
    async with db_engine.connect() as conn:
        res = await conn.execute(
            text(
                """
                SELECT privilege_type
                FROM information_schema.role_table_grants
                WHERE grantee = 'pdagent_app' AND table_name = 'audit_log'
                """
            )
        )
        privs = {str(r[0]) for r in res.all()}
        assert "SELECT" in privs
        assert "INSERT" in privs
        assert "UPDATE" not in privs
        assert "DELETE" not in privs
        assert row.id is not None


def test_two_org_cross_tenant_isolation_returns_404(
    test_settings: Settings,
    postgres_url: str,
) -> None:
    """Phases.md Phase 1 exit criterion: Org A token cannot read, list, or write to anything of Org
    B (404s).
    """
    _apply_migrations(postgres_url)
    app = create_app(test_settings)

    org_a = new_id()
    org_b = new_id()
    prop_a = new_id()
    prop_b = new_id()
    user_a = new_id()
    user_b = new_id()
    admin_a = new_id()
    admin_b = new_id()

    tok_tenant_a = mint_test_token(
        org_id=org_a, user_id=user_a, role="tenant", property_ids=[prop_a]
    )
    tok_tenant_b = mint_test_token(
        org_id=org_b, user_id=user_b, role="tenant", property_ids=[prop_b]
    )
    tok_admin_a = mint_test_token(
        org_id=org_a, user_id=admin_a, role="org_admin", property_ids=[prop_a]
    )
    tok_admin_b = mint_test_token(
        org_id=org_b, user_id=admin_b, role="org_admin", property_ids=[prop_b]
    )

    with TestClient(app) as client:
        # Org A creates a conversation and uploads a knowledge document
        conv_resp = client.post(
            "/v1/conversations",
            json={"channel": "web"},
            headers={"Authorization": f"Bearer {tok_tenant_a}"},
        )
        assert conv_resp.status_code == 201
        conv_a_id = conv_resp.json()["id"]

        doc_resp = client.post(
            "/v1/knowledge/documents",
            json={
                "title": "Org A Secret Handbook",
                "content": "# Quiet Hours\nQuiet hours start at 10pm.",
            },
            headers={"Authorization": f"Bearer {tok_admin_a}"},
        )
        assert doc_resp.status_code == 201
        doc_a_id = doc_resp.json()["id"]

        # Org B tries to read, message, or escalate Org A's conversation -> 404 NOT_FOUND
        assert (
            client.get(
                f"/v1/conversations/{conv_a_id}/messages",
                headers={"Authorization": f"Bearer {tok_tenant_b}"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/v1/conversations/{conv_a_id}/messages",
                json={"content": "Hello"},
                headers={
                    "Authorization": f"Bearer {tok_tenant_b}",
                    "Idempotency-Key": "idem-cross-org-1",
                },
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/v1/conversations/{conv_a_id}/handoff",
                headers={"Authorization": f"Bearer {tok_tenant_b}"},
            ).status_code
            == 404
        )

        # Org B admin tries to read or take Org A's conversation in inbox -> 404 NOT_FOUND
        assert (
            client.get(
                f"/v1/inbox/conversations/{conv_a_id}",
                headers={"Authorization": f"Bearer {tok_admin_b}"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/v1/inbox/conversations/{conv_a_id}/take",
                headers={"Authorization": f"Bearer {tok_admin_b}"},
            ).status_code
            == 404
        )

        # Org B admin lists documents -> sees 0 documents from Org A; deleting Org A's doc -> 404
        list_b = client.get(
            "/v1/knowledge/documents",
            headers={"Authorization": f"Bearer {tok_admin_b}"},
        )
        assert list_b.status_code == 200
        assert list_b.json()["items"] == []

        assert (
            client.delete(
                f"/v1/knowledge/documents/{doc_a_id}",
                headers={"Authorization": f"Bearer {tok_admin_b}"},
            ).status_code
            == 404
        )


@pytest.mark.asyncio
async def test_rls_blocks_query_without_tenant_transaction(
    db_engine: AsyncEngine,
    postgres_url: str,
) -> None:
    """Rules.md §1 Rule 2: verify_rls_context raises RuntimeError if app.org_id is not set."""
    _apply_migrations(postgres_url)
    session_factory = create_session_factory(db_engine)
    from pdagent.core.rls import verify_rls_context

    async with session_factory() as session:
        with pytest.raises(RuntimeError, match=r"app\.org_id"):
            await verify_rls_context(session)
