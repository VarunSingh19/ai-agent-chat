"""Phases 3, 4 & 5 tests: RAG replacement & degraded mode, MCP v2 contract, prompt injection, and
confirmations.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.testclient import TestClient

from pdagent.agent.canonical import ToolSpec
from pdagent.auth.principal import Principal
from pdagent.auth.token import mint_test_token
from pdagent.core.db import create_session_factory
from pdagent.core.ids import new_id, utc_now
from pdagent.core.rls import tenant_transaction
from pdagent.core.settings import Settings
from pdagent.knowledge.ingest.embed import EmbeddingClient
from pdagent.knowledge.retrieve import retrieve_knowledge_chunks
from pdagent.knowledge.service import KnowledgeService
from pdagent.main import create_app
from pdagent.mcp_server.pdapi_client import PropertyDekApiClient, WorkOrderRecord
from pdagent.mcp_server.server import StatelessMcpGateway
from pdagent.tools.confirm import ConfirmationRow, ConfirmationService
from pdagent.tools.registry import PERMANENTLY_FORBIDDEN_TOOLS, register_custom_tool
from pdagent.tools.schemas import ALL_TOOL_SPECS, FORBIDDEN_IDENTITY_FIELDS


def _apply_migrations(database_url: str) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def test_tool_schemas_never_contain_identity_fields_and_refuse_forbidden_tools() -> None:
    """Rules.md §1 Rules 1 & 4: Tool schemas never contain identity fields; forbidden tools are
    refused.
    """
    for name, spec in ALL_TOOL_SPECS.items():
        assert name not in PERMANENTLY_FORBIDDEN_TOOLS
        props = spec.parameters.get("properties", {})
        if isinstance(props, dict):
            assert not (set(props.keys()) & FORBIDDEN_IDENTITY_FIELDS)

    for forbidden_name in (
        "unlock_gate",
        "issue_refund",
        "waive_fee",
        "lease_change",
        "process_payment",
        "send_notice",
    ):
        with pytest.raises(PermissionError, match=r"Rules\.md §1 Rule 4"):
            register_custom_tool(
                ToolSpec(
                    name=forbidden_name,
                    description="Forbidden capability",
                    parameters={"type": "object", "properties": {}},
                )
            )


async def test_mcp_serves_2026_07_28_and_2025_11_25_and_blocks_other_tenant() -> None:
    """Phases.md Phase 4 exit criteria: MCP serves 2026-07-28 and 2025-11-25 clients; other
    tenant's WO is not_visible.
    """
    pdapi = PropertyDekApiClient()
    org_id = new_id()
    tenant_a = new_id()
    tenant_b = new_id()
    prop_id = new_id()

    pdapi.seed_work_order(
        WorkOrderRecord(
            request_id="WO-TENANT-B-99",
            org_id=org_id,
            user_id=tenant_b,
            property_id=prop_id,
            category="plumbing",
            urgency="routine",
            description="Tenant B private leak",
        )
    )
    gateway = StatelessMcpGateway(pdapi)
    principal_a = Principal(
        org_id=org_id,
        user_id=tenant_a,
        role="tenant",
        property_ids=(prop_id,),
        unit_id=None,
        jti="jti-a",
        raw_token="",
    )

    # 1. 2026-07-28 stateless discovery
    disc = await gateway.handle_jsonrpc(
        {"jsonrpc": "2.0", "id": 1, "method": "server/discover"},
        principal=principal_a,
    )
    assert disc["result"]["protocolVersion"] == "2026-07-28"  # type: ignore[index]
    assert disc["result"]["stateless"] is True  # type: ignore[index]

    # 2. 2025-11-25 legacy initialize + tools/list
    init_res = await gateway.handle_jsonrpc(
        {"jsonrpc": "2.0", "id": 2, "method": "initialize"},
        principal=principal_a,
    )
    assert init_res["result"]["protocolVersion"] == "2025-11-25"  # type: ignore[index]

    # 3. Prompt injection / cross-tenant lookup attempt for Tenant B's work order -> not_visible
    call_res = await gateway.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_request",
                "arguments": {"request_id": "WO-TENANT-B-99"},
            },
        },
        principal=principal_a,
    )
    assert call_res["result"]["data"] == {"status": "not_visible"}  # type: ignore[index]


async def test_knowledge_replacement_purges_old_chunks_and_degrades_when_embeddings_down(
    db_engine: AsyncEngine,
    postgres_url: str,
) -> None:
    """Phases.md Phase 3 exit criteria: replaced document's old chunks never appear; embedding
    outage returns full-text.
    """
    _apply_migrations(postgres_url)
    session_factory = create_session_factory(db_engine)
    org_id = new_id()
    prop_id = new_id()
    admin = Principal(
        org_id=org_id,
        user_id=new_id(),
        role="org_admin",
        property_ids=(prop_id,),
        unit_id=None,
        jti="jti-admin",
        raw_token="",
    )

    async with session_factory() as session, tenant_transaction(session, org_id):
        v1_doc = await KnowledgeService.upload_and_ingest(
            session,
            principal=admin,
            title="Guest Parking Policy",
            content_bytes=b"# Parking\nOvernight guests must park in Lot Blue.",
            property_id=prop_id,
        )
        v2_doc = await KnowledgeService.replace_document(
            session,
            principal=admin,
            old_document_id=v1_doc.id,
            title="Guest Parking Policy",
            content_bytes=b"# Parking\nOvernight guests must park in Garage Level 3.",
        )
        assert v2_doc.version == 2

        # Degraded retrieval when embedding service is down (`available=False`)
        down_embedder = EmbeddingClient(available=False)
        outcome = await retrieve_knowledge_chunks(
            session,
            principal=admin,
            query="Where do overnight guests park?",
            embedder=down_embedder,
        )
        assert outcome.degraded_retrieval is True
        assert len(outcome.chunks) == 1
        assert "Garage Level 3" in outcome.chunks[0].content
        assert "Lot Blue" not in outcome.chunks[0].content


async def test_confirmation_tampered_replayed_expired_and_other_user(
    test_settings: Settings,
    db_engine: AsyncEngine,
    postgres_url: str,
) -> None:
    """Phases.md Phase 5 exit criteria: tampered args, replay, expired, and other user fail
    cleanly.
    """
    _apply_migrations(postgres_url)
    app = create_app(test_settings)
    org_id = new_id()
    user_a = new_id()
    user_b = new_id()
    prop_id = new_id()

    tok_a = mint_test_token(org_id=org_id, user_id=user_a, role="tenant", property_ids=[prop_id])
    tok_b = mint_test_token(org_id=org_id, user_id=user_b, role="tenant", property_ids=[prop_id])

    with TestClient(app) as client:
        conv_resp = client.post(
            "/v1/conversations",
            json={"channel": "web"},
            headers={"Authorization": f"Bearer {tok_a}"},
        )
        conv_id = conv_resp.json()["id"]

        # Trigger write-tool confirmation card via conversation turn
        sse_resp = client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "Please submit a maintenance request for my leaking kitchen sink"},
            headers={
                "Authorization": f"Bearer {tok_a}",
                "Idempotency-Key": "turn-create-wo-1",
            },
        )
        assert sse_resp.status_code == 200
        assert "event: confirm.card" in sse_resp.text

        # Extract confirmation ID from DB
        session_factory = create_session_factory(db_engine)
        async with session_factory() as session, tenant_transaction(session, org_id):
            from sqlalchemy import select

            cards = list((await session.execute(select(ConfirmationRow))).scalars().all())
            assert len(cards) == 1
            conf_id = str(cards[0].id)

        # 1. Other user (`user_b`) attempting to confirm -> 404 NOT_FOUND
        other_resp = client.post(
            f"/v1/confirmations/{conf_id}/confirm",
            headers={
                "Authorization": f"Bearer {tok_b}",
                "Idempotency-Key": "confirm-other-user",
            },
        )
        assert other_resp.status_code == 404

        # 2. Tampered arguments hash -> 410 CONFIRMATION_EXPIRED
        tampered_resp = client.post(
            f"/v1/confirmations/{conf_id}/confirm",
            json={"args_hash": "0" * 64},
            headers={
                "Authorization": f"Bearer {tok_a}",
                "Idempotency-Key": "confirm-tampered",
            },
        )
        assert tampered_resp.status_code == 410
        assert tampered_resp.json()["code"] == "CONFIRMATION_EXPIRED"

        # Create a fresh pending card and confirm it idempotently
        async with session_factory() as session, tenant_transaction(session, org_id):
            principal_a = Principal(
                org_id=org_id,
                user_id=user_a,
                role="tenant",
                property_ids=(prop_id,),
                unit_id=None,
                jti="jti-a",
                raw_token="",
            )
            fresh_card = await ConfirmationService.create_pending_card(
                session,
                principal=principal_a,
                conversation_id=new_id(),
                tool_name="create_request",
                arguments={
                    "category": "plumbing",
                    "urgency": "routine",
                    "description": "Leaky faucet",
                },
            )
            fresh_id = str(fresh_card["id"])

        ok_resp_1 = client.post(
            f"/v1/confirmations/{fresh_id}/confirm",
            headers={
                "Authorization": f"Bearer {tok_a}",
                "Idempotency-Key": "confirm-valid-1",
            },
        )
        assert ok_resp_1.status_code == 200
        wo_id_1 = ok_resp_1.json()["result"]["request_id"]

        # Retrying with the SAME Idempotency-Key returns the exact same work order without creating
        # a second one
        ok_resp_retry = client.post(
            f"/v1/confirmations/{fresh_id}/confirm",
            headers={
                "Authorization": f"Bearer {tok_a}",
                "Idempotency-Key": "confirm-valid-1",
            },
        )
        assert ok_resp_retry.status_code == 200
        assert ok_resp_retry.json()["idempotent_replay"] is True
        assert ok_resp_retry.json()["result"]["request_id"] == wo_id_1

        # Replaying with a DIFFERENT Idempotency-Key after consumption -> 410 CONFIRMATION_EXPIRED
        replay_resp = client.post(
            f"/v1/confirmations/{fresh_id}/confirm",
            headers={
                "Authorization": f"Bearer {tok_a}",
                "Idempotency-Key": "confirm-replay-2",
            },
        )
        assert replay_resp.status_code == 410

        # Expired confirmation check
        async with session_factory() as session, tenant_transaction(session, org_id):
            exp_card = await ConfirmationService.create_pending_card(
                session,
                principal=principal_a,
                conversation_id=new_id(),
                tool_name="create_request",
                arguments={"category": "hvac", "urgency": "routine", "description": "Filter"},
            )
            exp_id = exp_card["id"]
            await session.execute(
                update(ConfirmationRow)
                .where(ConfirmationRow.id == exp_id)
                .values(expires_at=utc_now() - timedelta(minutes=1))
            )

        exp_resp = client.post(
            f"/v1/confirmations/{exp_id}/confirm",
            headers={
                "Authorization": f"Bearer {tok_a}",
                "Idempotency-Key": "confirm-expired-1",
            },
        )
        assert exp_resp.status_code == 410
