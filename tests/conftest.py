"""Pytest fixtures for Phase 0 unit and integration tests (Architecture.md §1 & §3).

Uses testcontainers PostgreSQL 18 + pgvector when a Docker daemon is reachable,
and falls back to the local PostgreSQL test database (PDAGENT_TEST_DATABASE_URL)
in containerised CI environments without a Docker socket.
"""

from __future__ import annotations

import subprocess
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine
from testcontainers.postgres import PostgresContainer

from pdagent.core.db import create_db_engine, normalize_async_db_url
from pdagent.core.settings import Settings
from pdagent.main import create_app

DEFAULT_LOCAL_TEST_DB = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/pdagent_test"
DEFAULT_LOCAL_REDIS = "redis://127.0.0.1:6379/0"


def _docker_daemon_available() -> bool:
    """Return True if a local Docker daemon is reachable for testcontainers."""
    try:
        proc = subprocess.run(
            ["docker", "info"],  # noqa: S607
            capture_output=True,
            timeout=2,
            check=False,
        )
        return proc.returncode == 0
    except Exception:
        return False


from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def postgres_db_url() -> Iterator[str]:
    """Provide a real PostgreSQL connection URL via testcontainers or local PG service."""
    if _docker_daemon_available():
        with PostgresContainer("pgvector/pgvector:0.8.1-pg18") as pg:
            raw_url: str = pg.get_connection_url()
            url = normalize_async_db_url(raw_url)
            alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
            alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
            alembic_cfg.set_main_option("sqlalchemy.url", url)
            command.upgrade(alembic_cfg, "head")
            yield url
    else:
        alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
        alembic_cfg.set_main_option("sqlalchemy.url", DEFAULT_LOCAL_TEST_DB)
        command.upgrade(alembic_cfg, "head")
        yield DEFAULT_LOCAL_TEST_DB


@pytest.fixture(scope="session")
def postgres_url(postgres_db_url: str) -> str:
    """Alias for postgres_db_url used across Phase 1-11 test suites."""
    return postgres_db_url


@pytest.fixture
def test_settings(postgres_db_url: str) -> Settings:
    """Return validated Settings pointing at the test PostgreSQL and Redis instances."""
    return Settings(
        database_url=postgres_db_url,
        migrator_database_url=postgres_db_url,
        redis_url=DEFAULT_LOCAL_REDIS,
        jwks_url="https://auth.propertydek.example.com/.well-known/jwks.json",
        token_issuer="https://auth.propertydek.example.com",
        token_audience="pdagent",
        environment="test",
    )


@pytest.fixture
async def db_engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Yield an async SQLAlchemy 2.1 psycopg 3 engine and dispose after test."""
    engine = create_db_engine(test_settings)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    """Yield a FastAPI TestClient running lifespan hooks."""
    app = create_app(test_settings)
    with TestClient(app) as test_client:
        yield test_client
