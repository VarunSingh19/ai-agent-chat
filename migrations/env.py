"""Alembic migration environment configured via pdagent.core.settings (psycopg 3)."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from pdagent.core.db import Base, normalize_async_db_url
from pdagent.core.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_migration_url() -> str:
    """Resolve the migrator database URL from Settings (Rules.md §4 & §5)."""
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return normalize_async_db_url(configured)
    settings = get_settings()
    raw = settings.migrator_database_url or settings.database_url
    return normalize_async_db_url(raw)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_migration_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using psycopg 3."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_migration_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
