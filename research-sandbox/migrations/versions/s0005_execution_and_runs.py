"""Create durable sandbox runs, status history, and artifact metadata.

Revision ID: s0005
Revises: s0004
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa


revision = "s0005"
down_revision = "s0004"
branch_labels = None
depends_on = None


RUN_STATUSES = (
    "pending_approval", "queued", "running", "completed_unvalidated", "failed",
    "timed_out", "policy_rejected", "cancelled",
)


def upgrade() -> None:
    op.create_table(
        "sandbox_runs",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("operation_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("plan_decision_id", sa.Uuid(), nullable=False),
        sa.Column("code_version_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("manifest_hash", sa.String(128), nullable=False),
        sa.Column("lease_owner", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["analysis_datasets.dataset_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["plan_id", "plan_version"],
            ["analysis_plan_versions.plan_id", "analysis_plan_versions.version"],
        ),
        sa.ForeignKeyConstraint(["plan_decision_id"], ["analysis_plan_decisions.decision_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["code_version_id"], ["analysis_code_versions.code_version_id"], ondelete="RESTRICT"),
        sa.CheckConstraint(f"status IN {RUN_STATUSES}", name="ck_sandbox_run_status"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_sandbox_run_idempotency"),
    )
    op.create_index("ix_sandbox_run_project_status", "sandbox_runs", ["project_id", "status"])
    op.create_index("ix_sandbox_run_lease", "sandbox_runs", ["status", "lease_expires_at"])

    op.create_table(
        "sandbox_run_status_history",
        sa.Column("history_id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("changed_by", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["sandbox_runs.run_id"], ondelete="CASCADE"),
        sa.CheckConstraint(f"to_status IN {RUN_STATUSES}", name="ck_sandbox_run_history_status"),
    )
    op.create_index("ix_sandbox_run_history_run", "sandbox_run_status_history", ["run_id", "created_at"])

    op.create_table(
        "analysis_artifacts",
        sa.Column("artifact_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["sandbox_runs.run_id"], ondelete="CASCADE"),
        sa.CheckConstraint("artifact_type IN ('result', 'table', 'chart', 'diagnostic')", name="ck_analysis_artifact_type"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_analysis_artifact_size"),
        sa.UniqueConstraint("run_id", "filename", name="uq_analysis_artifact_run_filename"),
    )
    op.create_index("ix_analysis_artifact_project_run", "analysis_artifacts", ["project_id", "run_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_artifact_project_run", table_name="analysis_artifacts")
    op.drop_table("analysis_artifacts")
    op.drop_index("ix_sandbox_run_history_run", table_name="sandbox_run_status_history")
    op.drop_table("sandbox_run_status_history")
    op.drop_index("ix_sandbox_run_lease", table_name="sandbox_runs")
    op.drop_index("ix_sandbox_run_project_status", table_name="sandbox_runs")
    op.drop_table("sandbox_runs")
