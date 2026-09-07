"""Create session, trusted-context, operation, and audit records.

Revision ID: s0001
Revises:
Create Date: 2026-08-15
"""

from alembic import op
import sqlalchemy as sa


revision = "s0001"
down_revision = None
branch_labels = None
depends_on = None


SESSION_STATUSES = (
    "draft", "context_ready", "active", "waiting_for_user", "completed",
    "discarded", "stale", "failed",
)
MODES = ("hypothesis", "graph_overlay", "data_analysis")
ENTRYPOINTS = ("manual", "graphrag_answer", "validated_candidate", "experiment_proposal")


def upgrade() -> None:
    op.create_table(
        "research_sandbox_context_snapshots",
        sa.Column("context_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_resource_id", sa.String(255), nullable=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"source_type IN {ENTRYPOINTS}", name="ck_sandbox_context_source_type"),
        sa.UniqueConstraint("project_id", "context_id", name="uq_sandbox_context_project_id"),
    )
    op.create_index("ix_sandbox_context_project_hash", "research_sandbox_context_snapshots", ["project_id", "content_hash"])

    op.create_table(
        "research_sandbox_sessions",
        sa.Column("session_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("entrypoint", sa.String(64), nullable=False),
        sa.Column("source_resource_id", sa.String(255), nullable=True),
        sa.Column("source_version", sa.String(255), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("initial_question", sa.Text(), nullable=True),
        sa.Column("creator_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("context_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("context_hash", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"mode IN {MODES}", name="ck_sandbox_session_mode"),
        sa.CheckConstraint(f"entrypoint IN {ENTRYPOINTS}", name="ck_sandbox_session_entrypoint"),
        sa.CheckConstraint(f"status IN {SESSION_STATUSES}", name="ck_sandbox_session_status"),
        sa.ForeignKeyConstraint(["context_snapshot_id"], ["research_sandbox_context_snapshots.context_id"]),
        sa.UniqueConstraint("project_id", "session_id", name="uq_sandbox_session_project_id"),
    )
    op.create_index("ix_sandbox_sessions_project_status", "research_sandbox_sessions", ["project_id", "status"])

    op.create_table(
        "research_sandbox_session_status_history",
        sa.Column("history_id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("changed_by", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["research_sandbox_sessions.session_id"], ondelete="CASCADE"),
        sa.CheckConstraint(f"to_status IN {SESSION_STATUSES}", name="ck_sandbox_history_to_status"),
    )
    op.create_index("ix_sandbox_session_history_session", "research_sandbox_session_status_history", ["session_id", "created_at"])

    op.create_table(
        "sandbox_operations",
        sa.Column("operation_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("operation_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["research_sandbox_sessions.session_id"], ondelete="SET NULL"),
    )
    op.create_index("ix_sandbox_operations_project_session", "sandbox_operations", ["project_id", "session_id"])

    op.create_table(
        "sandbox_audit_events",
        sa.Column("audit_event_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.String(255), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("correlation_id", sa.String(255), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["research_sandbox_sessions.session_id"], ondelete="SET NULL"),
    )
    op.create_index("ix_sandbox_audit_project_created", "sandbox_audit_events", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_sandbox_audit_project_created", table_name="sandbox_audit_events")
    op.drop_table("sandbox_audit_events")
    op.drop_index("ix_sandbox_operations_project_session", table_name="sandbox_operations")
    op.drop_table("sandbox_operations")
    op.drop_index("ix_sandbox_session_history_session", table_name="research_sandbox_session_status_history")
    op.drop_table("research_sandbox_session_status_history")
    op.drop_index("ix_sandbox_sessions_project_status", table_name="research_sandbox_sessions")
    op.drop_table("research_sandbox_sessions")
    op.drop_index("ix_sandbox_context_project_hash", table_name="research_sandbox_context_snapshots")
    op.drop_table("research_sandbox_context_snapshots")
