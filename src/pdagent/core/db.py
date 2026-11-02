"""Async SQLAlchemy 2.1 + psycopg 3 database engine and readiness checks (Architecture.md §1)."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from pdagent.core.settings import Settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy models."""


def normalize_async_db_url(url: str) -> str:
    """Ensure PostgreSQL URLs use the psycopg 3 driver (`postgresql+psycopg://`).

    Rules.md §2 forbids psycopg2 and asyncpg; SQLAlchemy 2.1 uses psycopg 3.
    """
    cleaned = url.strip()
    if cleaned.startswith(("postgresql+psycopg2://", "postgresql+asyncpg://")):
        msg = "psycopg2 and asyncpg are forbidden by Rules.md §2; use postgresql+psycopg://"
        raise ValueError(msg)
    if cleaned.startswith("postgres://"):
        return "postgresql+psycopg://" + cleaned.removeprefix("postgres://")
    if cleaned.startswith("postgresql://"):
        return "postgresql+psycopg://" + cleaned.removeprefix("postgresql://")
    return cleaned


def create_db_engine(settings: Settings) -> AsyncEngine:
    """Create an async SQLAlchemy 2.1 engine using psycopg 3."""
    async_url = normalize_async_db_url(settings.database_url)
    return create_async_engine(
        async_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async sessionmaker bound to the given engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def check_db_ready(engine: AsyncEngine, timeout_s: float = 2.0) -> bool:
    """Run a lightweight connectivity check (`SELECT 1`) against PostgreSQL."""
    try:
        async with asyncio.timeout(timeout_s), engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception:
        logger.warning("Database readiness check failed")
        return False
