"""Create sandbox dataset metadata, immutable profiles, and analysis questions.

Revision ID: s0003
Revises: s0002
Create Date: 2026-08-15
"""

from alembic import op
import sqlalchemy as sa


revision = "s0003"
down_revision = "s0002"
branch_labels = None
depends_on = None


DATASET_CLASSIFICATIONS = ("non_sensitive", "unknown", "restricted")
DATASET_STATUSES = ("staged", "validated", "rejected", "deleted")
QUESTION_STATUSES = ("draft", "question_incomplete")
OBJECTIVES = ("describe", "compare", "associate", "predict")


def upgrade() -> None:
    op.create_table(
        "analysis_datasets",
        sa.Column("dataset_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("size_bytes >= 0", name="ck_analysis_dataset_size"),
        sa.CheckConstraint(f"classification IN {DATASET_CLASSIFICATIONS}", name="ck_analysis_dataset_classification"),
        sa.CheckConstraint(f"status IN {DATASET_STATUSES}", name="ck_analysis_dataset_status"),
        sa.UniqueConstraint("project_id", "dataset_id", name="uq_analysis_dataset_project_id"),
    )
    op.create_index("ix_analysis_dataset_project_hash", "analysis_datasets", ["project_id", "content_hash"])

    op.create_table(
        "analysis_dataset_profiles",
        sa.Column("profile_id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("profiler_version", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("columns_json", sa.JSON(), nullable=False),
        sa.Column("profile_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["analysis_datasets.dataset_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("version >= 1", name="ck_analysis_profile_version"),
        sa.CheckConstraint("row_count >= 0", name="ck_analysis_profile_rows"),
        sa.CheckConstraint("column_count >= 0", name="ck_analysis_profile_columns"),
        sa.UniqueConstraint("dataset_id", "version", name="uq_analysis_profile_dataset_version"),
        sa.UniqueConstraint("dataset_id", "content_hash", "profiler_version", name="uq_analysis_profile_immutable_input"),
    )
    op.create_index("ix_analysis_profile_project_dataset", "analysis_dataset_profiles", ["project_id", "dataset_id"])

    op.create_table(
        "analysis_questions",
        sa.Column("question_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("objective", sa.String(32), nullable=False),
        sa.Column("research_question", sa.Text(), nullable=False),
        sa.Column("outcome_columns", sa.JSON(), nullable=False),
        sa.Column("predictor_columns", sa.JSON(), nullable=False),
        sa.Column("group_columns", sa.JSON(), nullable=False),
        sa.Column("covariate_columns", sa.JSON(), nullable=False),
        sa.Column("study_design", sa.Text(), nullable=True),
        sa.Column("repeated_measures", sa.Boolean(), nullable=True),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("preferred_metrics", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["analysis_datasets.dataset_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("version >= 1", name="ck_analysis_question_version"),
        sa.CheckConstraint(f"objective IN {OBJECTIVES}", name="ck_analysis_question_objective"),
        sa.CheckConstraint(f"status IN {QUESTION_STATUSES}", name="ck_analysis_question_status"),
        sa.UniqueConstraint("question_id", "version", name="uq_analysis_question_version"),
    )
    op.create_index("ix_analysis_question_project_dataset", "analysis_questions", ["project_id", "dataset_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_question_project_dataset", table_name="analysis_questions")
    op.drop_table("analysis_questions")
    op.drop_index("ix_analysis_profile_project_dataset", table_name="analysis_dataset_profiles")
    op.drop_table("analysis_dataset_profiles")
    op.drop_index("ix_analysis_dataset_project_hash", table_name="analysis_datasets")
    op.drop_table("analysis_datasets")
