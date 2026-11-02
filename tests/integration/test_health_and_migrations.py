"""Integration tests for /healthz, /readyz (with Redis down), and Alembic migrations (Phase 0)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from pdagent.core.settings import Settings
from pdagent.main import create_app


class _FailingRedisClient:
    """Fake Redis client simulating a stopped Redis instance."""

    async def ping(self) -> bool:
        msg = "Connection refused: Redis stopped"
        raise ConnectionError(msg)

    async def aclose(self) -> None:
        return None


def test_healthz_and_readyz_when_db_and_redis_up(client: TestClient) -> None:
    health_res = client.get("/healthz")
    assert health_res.status_code == 200
    assert health_res.json() == {"status": "ok"}
    assert "X-Request-ID" in health_res.headers

    ready_res = client.get("/readyz")
    assert ready_res.status_code == 200
    assert ready_res.json() == {
        "status": "ready",
        "checks": {"db": "ok", "redis": "ok"},
    }


def test_readyz_returns_503_when_redis_stopped_while_healthz_returns_200(
    test_settings: Settings,
) -> None:
    """Verify the Phase 0 rule: when Redis is stopped, /readyz returns 503 with a stable
    body and /healthz still returns 200 so emergency traffic is not cut off.
    """
    app = create_app(test_settings, redis_client_override=_FailingRedisClient())
    with TestClient(app) as test_client:
        ready_res = test_client.get("/readyz")
        assert ready_res.status_code == 503
        assert ready_res.headers["content-type"].startswith("application/problem+json")
        body = ready_res.json()
        assert body["code"] == "PROVIDER_UNAVAILABLE"
        assert body["status"] == 503
        assert body["checks"] == {"db": "ok", "redis": "down"}
        assert body["request_id"]

        health_res = test_client.get("/healthz")
        assert health_res.status_code == 200
        assert health_res.json() == {"status": "ok"}


def test_readyz_returns_503_when_db_down(test_settings: Settings) -> None:
    async def _failing_db() -> bool:
        return False

    app = create_app(test_settings, db_check_override=_failing_db)
    with TestClient(app) as test_client:
        ready_res = test_client.get("/readyz")
        assert ready_res.status_code == 503
        body = ready_res.json()
        assert body["checks"] == {"db": "down", "redis": "ok"}


REPO_ROOT = Path(__file__).resolve().parents[2]


async def test_alembic_migration_upgrade_and_downgrade_one_step(
    postgres_db_url: str,
    db_engine: AsyncEngine,
) -> None:
    """Verify migrations apply cleanly, roll back one step (-1) and to base, and reapply."""
    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", postgres_db_url)

    # 1. Upgrade to head (0002_phase1_to_9_schema)
    command.upgrade(alembic_cfg, "head")

    async with db_engine.connect() as conn:
        res_eval = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'evals' AND table_name = 'eval_runs'"
            )
        )
        assert res_eval.scalar() == "eval_runs"
        res_conv = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'conversations'"
            )
        )
        assert res_conv.scalar() == "conversations"

    # 2. Downgrade one step (-1 -> 0001_phase0_baseline)
    command.downgrade(alembic_cfg, "-1")

    async with db_engine.connect() as conn:
        res_conv_after_step = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'conversations'"
            )
        )
        assert res_conv_after_step.scalar() is None

    # 3. Downgrade one more step (-1 -> base)
    command.downgrade(alembic_cfg, "-1")

    async with db_engine.connect() as conn:
        res_after_down = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'evals' AND table_name = 'eval_runs'"
            )
        )
        assert res_after_down.scalar() is None

    # 4. Re-upgrade to head so the test database stays at head
    command.upgrade(alembic_cfg, "head")
