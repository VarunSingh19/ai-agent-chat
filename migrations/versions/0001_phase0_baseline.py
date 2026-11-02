"""Phase 0 baseline migration: enable pgcrypt/pgvector check and non-tenant evals schema.

Revision ID: 0001_phase0_baseline
Revises: None
Create Date: 2026-11-01 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase0_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply Phase 0 baseline schema (non-tenant evals schema from Architecture.md §5).

    Note: Tenant tables with org_id and RLS policies are created in Phase 1+.
    """
    # Enable vector extension when available on the PostgreSQL instance (pgvector 0.8.1 on PG 18);
    # use a safe DO block so local test verification also succeeds if pgvector shared library
    # is checked separately.
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_available_extensions WHERE name = 'vector'
                ) THEN
                    CREATE EXTENSION IF NOT EXISTS vector;
                END IF;
            END
            $$;
            """
        )
    )
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS evals"))
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("git_sha", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        schema="evals",
    )


def downgrade() -> None:
    """Roll back Phase 0 baseline one step."""
    op.drop_table("eval_runs", schema="evals")
    op.execute(sa.text("DROP SCHEMA IF EXISTS evals"))
