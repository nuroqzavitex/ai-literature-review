"""Create immutable analysis-plan, decision, and generated-code versions.

Revision ID: s0004
Revises: s0003
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa


revision = "s0004"
down_revision = "s0003"
branch_labels = None
depends_on = None


PLAN_STATUSES = ("draft", "in_review", "approved", "rejected", "changes_requested", "superseded")
DECISION_STATUSES = ("in_review", "approved", "rejected", "changes_requested")
CODE_STATUSES = ("draft", "policy_rejected", "approved", "superseded")


def upgrade() -> None:
    # Context remains a pinned external reference: no raw GraphRAG/Discovery content is copied here.
    op.add_column("analysis_questions", sa.Column("context_snapshot_id", sa.Uuid(), nullable=True))
    op.add_column("analysis_questions", sa.Column("context_hash", sa.String(128), nullable=True))
    op.create_table(
        "analysis_plan_versions",
        sa.Column("plan_version_id", sa.Uuid(), primary_key=True),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("question_version", sa.Integer(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("context_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("context_hash", sa.String(128), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("objective", sa.String(32), nullable=False),
        sa.Column("research_question", sa.Text(), nullable=False),
        sa.Column("outcome_columns", sa.JSON(), nullable=False),
        sa.Column("predictor_columns", sa.JSON(), nullable=False),
        sa.Column("group_columns", sa.JSON(), nullable=False),
        sa.Column("covariate_columns", sa.JSON(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("method_rationale", sa.Text(), nullable=False),
        sa.Column("preprocessing_steps", sa.JSON(), nullable=False),
        sa.Column("assumption_checks", sa.JSON(), nullable=False),
        sa.Column("evaluation_metrics", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("plan_hash", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["analysis_datasets.dataset_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["question_id"], ["analysis_questions.question_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("version >= 1", name="ck_analysis_plan_version"),
        sa.CheckConstraint(f"status IN {PLAN_STATUSES}", name="ck_analysis_plan_status"),
        sa.CheckConstraint("objective IN ('describe', 'compare', 'associate', 'predict')", name="ck_analysis_plan_objective"),
        sa.UniqueConstraint("plan_id", "version", name="uq_analysis_plan_version"),
    )
    op.create_index("ix_analysis_plan_project_dataset", "analysis_plan_versions", ["project_id", "dataset_id"])
    op.create_index("ix_analysis_plan_project_hash", "analysis_plan_versions", ["project_id", "plan_hash"])

    op.create_table(
        "analysis_plan_decisions",
        sa.Column("decision_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.String(255), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id", "plan_version"],
            ["analysis_plan_versions.plan_id", "analysis_plan_versions.version"],
        ),
        sa.CheckConstraint(f"decision IN {DECISION_STATUSES}", name="ck_analysis_plan_decision"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_analysis_plan_decision_idempotency"),
    )
    op.create_index("ix_analysis_plan_decision_plan", "analysis_plan_decisions", ["plan_id", "plan_version", "created_at"])

    op.create_table(
        "analysis_code_versions",
        sa.Column("code_version_id", sa.Uuid(), primary_key=True),
        sa.Column("code_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id", "plan_version"],
            ["analysis_plan_versions.plan_id", "analysis_plan_versions.version"],
        ),
        sa.CheckConstraint("version >= 1", name="ck_analysis_code_version"),
        sa.CheckConstraint(f"status IN {CODE_STATUSES}", name="ck_analysis_code_status"),
        sa.UniqueConstraint("code_id", "version", name="uq_analysis_code_version"),
    )
    op.create_index("ix_analysis_code_project_plan", "analysis_code_versions", ["project_id", "plan_id", "plan_version"])


def downgrade() -> None:
    op.drop_index("ix_analysis_code_project_plan", table_name="analysis_code_versions")
    op.drop_table("analysis_code_versions")
    op.drop_index("ix_analysis_plan_decision_plan", table_name="analysis_plan_decisions")
    op.drop_table("analysis_plan_decisions")
    op.drop_index("ix_analysis_plan_project_hash", table_name="analysis_plan_versions")
    op.drop_index("ix_analysis_plan_project_dataset", table_name="analysis_plan_versions")
    op.drop_table("analysis_plan_versions")
    op.drop_column("analysis_questions", "context_hash")
    op.drop_column("analysis_questions", "context_snapshot_id")
