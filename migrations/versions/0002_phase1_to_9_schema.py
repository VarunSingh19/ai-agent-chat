"""Phase 1 through Phase 9 tenant tables with strict Row-Level Security (RLS) policies.

Revision ID: 0002_phase1_to_9_schema
Revises: 0001_phase0_baseline
Create Date: 2026-11-01 12:00:00+00:00

Rules.md §1 Rule 2: Never add a table with `org_id` and no RLS policy in the same migration.
Every tenant table below is created alongside `ENABLE ROW LEVEL SECURITY`,
`FORCE ROW LEVEL SECURITY`, and a tenant isolation policy bound to
`current_setting('app.org_id', true)::uuid` in this single transactional revision.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_phase1_to_9_schema"
down_revision: str | None = "0001_phase0_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES: tuple[str, ...] = (
    "org_settings",
    "audit_log",
    "conversations",
    "messages",
    "documents",
    "document_chunks",
    "confirmations",
    "handoffs",
    "sms_opt_outs",
    "triage_drafts",
)


def _enable_rls(table_name: str) -> None:
    op.execute(sa.text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY"))
    op.execute(
        sa.text(
            f"""
            CREATE POLICY {table_name}_tenant_isolation ON {table_name}
            USING (
                NULLIF(current_setting('app.org_id', true), '') IS NOT NULL
                AND org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            )
            WITH CHECK (
                NULLIF(current_setting('app.org_id', true), '') IS NOT NULL
                AND org_id = NULLIF(current_setting('app.org_id', true), '')::uuid
            )
            """
        )
    )


def upgrade() -> None:
    """Create non-superuser app role and all tenant tables with mandatory RLS policies."""
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pdagent_app') THEN
                    CREATE ROLE pdagent_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                END IF;
            END
            $$;
            """
        )
    )

    # 1. org_settings (Phase 1 & Phase 10)
    op.create_table(
        "org_settings",
        sa.Column("org_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("tone", sa.String(length=32), nullable=False, server_default="professional"),
        sa.Column("enabled_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("handoff_timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("daily_budget_usd", sa.Float(), nullable=False, server_default="25.0"),
        sa.Column("user_daily_budget_usd", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column(
            "emergency_phone",
            sa.String(length=64),
            nullable=False,
            server_default="1-800-555-0199",
        ),
        sa.Column("prompt_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    _enable_rls("org_settings")

    # 2. audit_log (Phase 1 — append-only)
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    _enable_rls("audit_log")

    # 3. conversations (Phase 2 & Phase 6)
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False, server_default="web"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ai"),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rolling_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("unhelpful_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_seq", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    _enable_rls("conversations")

    # 4. messages (Phase 2)
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("sender_role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("route", sa.String(length=32), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failover", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sources_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_messages_conversation_seq"),
    )
    _enable_rls("messages")

    # 5. documents (Phase 3 RAG)
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("failure_reason", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    _enable_rls("documents")

    # 6. document_chunks (Phase 3 RAG)
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading_path", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    _enable_rls("document_chunks")

    # 7. confirmations (Phase 5 write tools)
    op.create_table(
        "confirmations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("args_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("args_hash", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    _enable_rls("confirmations")

    # 8. handoffs (Phase 6 emergency & human takeover)
    op.create_table(
        "handoffs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("is_emergency", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("matched_rule", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="waiting"),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("timeout_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    _enable_rls("handoffs")

    # 9. sms_opt_outs (Phase 8 SMS compliance)
    op.create_table(
        "sms_opt_outs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("phone_hash", sa.String(length=64), nullable=False, index=True),
        sa.Column("opted_out", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("org_id", "phone_hash", name="uq_sms_opt_outs_org_phone"),
    )
    _enable_rls("sms_opt_outs")

    # 10. triage_drafts (Phase 9 maintenance triage from photos)
    op.create_table(
        "triage_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("property_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("urgency", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("follow_up_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("photo_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("image_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_staff"),
        sa.Column("work_order_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    _enable_rls("triage_drafts")

    # Grant table permissions to pdagent_app; audit_log is strictly append-only (SELECT, INSERT
    # only)
    for tbl in TENANT_TABLES:
        if tbl == "audit_log":
            op.execute(sa.text("GRANT SELECT, INSERT ON TABLE audit_log TO pdagent_app"))
            op.execute(
                sa.text("REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_log FROM pdagent_app")
            )
        else:
            op.execute(
                sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {tbl} TO pdagent_app")
            )


def downgrade() -> None:
    """Drop all Phase 1-9 tenant tables in reverse dependency order."""
    for tbl in reversed(TENANT_TABLES):
        op.drop_table(tbl)
