"""Phases 6, 8, 9, 10 & 11 tests: Emergency with providers down, Staff takeover 409, SMS
STOP/START, Triage, Settings, and PhaseGateMonitorAgent.
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.testclient import TestClient

from pdagent.agent.providers.base import ProviderGateway, load_model_catalog
from pdagent.agent.providers.fake import FakeLLMProvider
from pdagent.auth.principal import Principal
from pdagent.auth.token import mint_test_token
from pdagent.core.db import create_session_factory
from pdagent.core.ids import new_id
from pdagent.core.rls import tenant_transaction
from pdagent.core.settings import Settings
from pdagent.evals.report import PhaseGateMonitorAgent
from pdagent.main import create_app
from pdagent.triage.schemas import PhotoDescriptor
from pdagent.triage.service import TriageService
from pdagent.workers.periodic import run_org_periodic_maintenance


def _apply_migrations(database_url: str) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def test_emergency_bypasses_all_down_providers_and_staff_takeover_409(
    test_settings: Settings,
    postgres_url: str,
) -> None:
    """Phases.md Phase 6 exit criteria:
    - With all providers down, an emergency phrase triggers a staff alert and safety reply.
    - Two staff members taking the same thread yield one winner and one 409 CONFLICT_TAKEN.
    - AI never replies while a thread is `staff`.
    """
    _apply_migrations(postgres_url)
    app = create_app(test_settings)

    org_id = new_id()
    prop_id = new_id()
    tenant_id = new_id()
    staff_1 = new_id()
    staff_2 = new_id()

    tok_tenant = mint_test_token(
        org_id=org_id, user_id=tenant_id, role="tenant", property_ids=[prop_id]
    )
    tok_staff_1 = mint_test_token(
        org_id=org_id, user_id=staff_1, role="pm_member", property_ids=[prop_id]
    )
    tok_staff_2 = mint_test_token(
        org_id=org_id, user_id=staff_2, role="pm_member", property_ids=[prop_id]
    )

    with TestClient(app) as client:
        # Force all 3 LLM providers (Anthropic, OpenAI, Gemini) to fail
        app.state.provider_gateway = ProviderGateway(
            providers={
                "anthropic": FakeLLMProvider(
                    provider_name="anthropic", fail_before_first_token=True
                ),
                "openai": FakeLLMProvider(provider_name="openai", fail_before_first_token=True),
                "gemini": FakeLLMProvider(provider_name="gemini", fail_before_first_token=True),
            },
            catalog=load_model_catalog(),
        )

        conv_resp = client.post(
            "/v1/conversations",
            json={"channel": "web"},
            headers={"Authorization": f"Bearer {tok_tenant}"},
        )
        conv_id = conv_resp.json()["id"]

        # Send emergency message while all LLM providers are down
        emg_resp = client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "I smell gas in the hallway near the boiler room!"},
            headers={
                "Authorization": f"Bearer {tok_tenant}",
                "Idempotency-Key": "emg-gas-turn-1",
            },
        )
        assert emg_resp.status_code == 200
        assert "911" in emg_resp.text
        assert "event: handoff" in emg_resp.text
        assert len(app.state.staff_notifier.events) >= 1
        assert app.state.staff_notifier.events[-1].is_emergency is True

        # Staff 1 and Staff 2 both try to take the same waiting thread -> one 200, one 409
        # CONFLICT_TAKEN
        take_1 = client.post(
            f"/v1/inbox/conversations/{conv_id}/take",
            headers={"Authorization": f"Bearer {tok_staff_1}"},
        )
        take_2 = client.post(
            f"/v1/inbox/conversations/{conv_id}/take",
            headers={"Authorization": f"Bearer {tok_staff_2}"},
        )
        assert take_1.status_code == 200
        assert take_2.status_code == 409
        assert take_2.json()["code"] == "CONFLICT_TAKEN"

        # While status == 'staff', tenant sends another message -> AI stays silent (no token events)
        while_staff_resp = client.post(
            f"/v1/conversations/{conv_id}/messages",
            json={"content": "I am outside now."},
            headers={
                "Authorization": f"Bearer {tok_tenant}",
                "Idempotency-Key": "while-staff-turn-2",
            },
        )
        assert while_staff_resp.status_code == 200
        assert "event: token" not in while_staff_resp.text


def test_sms_stop_start_anonymous_and_replay_protection(
    test_settings: Settings,
    postgres_url: str,
) -> None:
    """Phases.md Phase 8 exit criteria: STOP suppresses outbound until START; unknown number gets
    FAQ only; replay ignored.
    """
    _apply_migrations(postgres_url)
    app = create_app(test_settings)
    org_id = new_id()
    phone = "+14155550144"

    with TestClient(app) as client:
        adapter = app.state.sms_adapter

        def _send_sms(sid: str, body: str) -> dict[str, object]:
            sig = adapter.compute_signature(sid, phone, body)
            r = client.post(
                "/v1/channels/sms/inbound",
                json={
                    "org_id": str(org_id),
                    "message_sid": sid,
                    "from_phone": phone,
                    "body": body,
                },
                headers={"X-Sms-Signature": sig},
            )
            assert r.status_code == 200
            return dict(r.json())

        # 1. Unknown number -> anonymous FAQ mode, no personal data
        res_anon = _send_sms("SM001", "What is my rent balance?")
        assert res_anon["status"] == "anonymous_faq"
        assert res_anon["anonymous_mode"] is True

        # 2. Replay of SM001 -> duplicate_ignored, no duplicate message
        res_replay = _send_sms("SM001", "What is my rent balance?")
        assert res_replay["status"] == "duplicate_ignored"
        assert res_replay["replayed"] is True

        # 3. STOP -> opted_out, and subsequent messages send no outbound SMS
        res_stop = _send_sms("SM002", "STOP")
        assert res_stop["status"] == "opted_out"
        assert res_stop["outbound_sent"] is False

        res_blocked = _send_sms("SM003", "Hello again")
        assert res_blocked["status"] == "suppressed_opted_out"
        assert res_blocked["outbound_sent"] is False

        # 4. START -> re-enables outbound messages
        res_start = _send_sms("SM004", "START")
        assert res_start["status"] == "opted_in"
        assert res_start["outbound_sent"] is True


async def test_photo_triage_emergency_first_and_staff_approval_creates_one_work_order(
    db_engine: AsyncEngine,
    postgres_url: str,
) -> None:
    """Phases.md Phase 9 exit criteria: emergency photo description hits emergency rules first;
    approval creates 1 WO.
    """
    _apply_migrations(postgres_url)
    session_factory = create_session_factory(db_engine)
    org_id = new_id()
    prop_id = new_id()
    tenant = Principal(
        org_id=org_id,
        user_id=new_id(),
        role="tenant",
        property_ids=(prop_id,),
        unit_id=None,
        jti="jti-t",
        raw_token="",
    )
    staff = Principal(
        org_id=org_id,
        user_id=new_id(),
        role="pm_member",
        property_ids=(prop_id,),
        unit_id=None,
        jti="jti-s",
        raw_token="",
    )
    photo = PhotoDescriptor(
        object_key="photos/sink-leak-1.jpg",
        content_type="image/jpeg",
        size_bytes=240_000,
        width_px=800,
        height_px=600,
    )

    from pdagent.mcp_server.pdapi_client import PropertyDekApiClient

    pdapi = PropertyDekApiClient()

    async with session_factory() as session, tenant_transaction(session, org_id):
        # 1. Emergency description in photo triage bypasses model and triggers emergency reply
        emg_draft = await TriageService.create_triage_draft(
            session,
            principal=tenant,
            description="Flames coming out of the kitchen stove outlet",
            photos=[photo],
        )
        assert emg_draft["is_emergency"] is True
        assert emg_draft["draft_id"] is None

        # 2. Normal photo triage creates a pending_staff draft with <= 2 follow-up questions
        normal_draft = await TriageService.create_triage_draft(
            session,
            principal=tenant,
            description="Slow drip under the bathroom sink P-trap",
            photos=[photo],
        )
        assert normal_draft["status"] == "pending_staff"
        assert len(normal_draft["follow_up_questions"]) <= 2  # type: ignore[arg-type]
        draft_uuid = new_id()
        from uuid import UUID

        draft_uuid = UUID(str(normal_draft["draft_id"]))

        # 3. Staff approval creates exactly one work order (even if approved twice)
        app_1 = await TriageService.approve_draft(
            session, principal=staff, draft_id=draft_uuid, pdapi=pdapi
        )
        app_2 = await TriageService.approve_draft(
            session, principal=staff, draft_id=draft_uuid, pdapi=pdapi
        )
        assert app_1["work_order_id"] == app_2["work_order_id"]
        assert app_2["idempotent_replay"] is True

        # Run periodic maintenance worker task
        maint = await run_org_periodic_maintenance(session, org_id=org_id)
        assert "timed_out_handoffs" in maint


def test_org_settings_and_fbc_operator_usage_and_phase_gate_monitor_agent(
    test_settings: Settings,
    postgres_url: str,
) -> None:
    """Phases.md Phase 10 & 11: Org settings update, fbc_operator redacted usage, and
    PhaseGateMonitorAgent approval.
    """
    _apply_migrations(postgres_url)
    app = create_app(test_settings)
    org_id = new_id()
    admin_tok = mint_test_token(org_id=org_id, user_id=new_id(), role="org_admin")
    operator_tok = mint_test_token(org_id=org_id, user_id=new_id(), role="fbc_operator")

    with TestClient(app) as client:
        put_resp = client.put(
            "/v1/settings/agent",
            json={"daily_budget_usd": 40.0, "tone": "warm"},
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["daily_budget_usd"] == 40.0

        # fbc_operator receives hashed org aggregates only (org_id stripped)
        op_usage = client.get(
            "/v1/admin/usage",
            headers={"Authorization": f"Bearer {operator_tok}"},
        )
        assert op_usage.status_code == 200
        assert "org_hash" in op_usage.json()
        assert "org_id" not in op_usage.json()

    # Run the automated PhaseGateMonitorAgent across Phases 0-11
    monitor = PhaseGateMonitorAgent()
    report = monitor.evaluate_all_phases()
    assert report.overall_verdict == "APPROVED"
    assert report.passed_checks == report.total_checks
    assert report.eval_pass_rate == 1.0
