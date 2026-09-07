"""Create validation, review, citation, and sealed reproducibility records.

Revision ID: s0006
Revises: s0005
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa


revision = "s0006"
down_revision = "s0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    s6_run_statuses = (
        "pending_approval", "queued", "running", "completed_unvalidated", "validation_failed",
        "result_review_waiting", "approved", "rejected", "failed", "timed_out", "policy_rejected", "cancelled",
    )
    op.drop_constraint("ck_sandbox_run_status", "sandbox_runs", type_="check")
    op.create_check_constraint("ck_sandbox_run_status", "sandbox_runs", f"status IN {s6_run_statuses}")
    op.drop_constraint("ck_sandbox_run_history_status", "sandbox_run_status_history", type_="check")
    op.create_check_constraint("ck_sandbox_run_history_status", "sandbox_run_status_history", f"to_status IN {s6_run_statuses}")
    op.create_table(
        "analysis_result_validations",
        sa.Column("validation_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("result_hash", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("validator_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["sandbox_runs.run_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("status IN ('validated', 'failed')", name="ck_result_validation_status"),
        sa.UniqueConstraint("run_id", name="uq_result_validation_run"),
    )
    op.create_index("ix_result_validation_project_run", "analysis_result_validations", ["project_id", "run_id"])

    op.create_table(
        "analysis_result_reviews",
        sa.Column("review_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("validation_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.String(255), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["sandbox_runs.run_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["validation_id"], ["analysis_result_validations.validation_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_result_review_decision"),
        sa.UniqueConstraint("project_id", "idempotency_key", name="uq_result_review_idempotency"),
    )
    op.create_index("ix_result_review_project_run", "analysis_result_reviews", ["project_id", "run_id", "created_at"])

    op.create_table(
        "analysis_citations",
        sa.Column("citation_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_hash", sa.String(128), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=True),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("locator", sa.String(1024), nullable=False),
        sa.Column("value_hash", sa.String(128), nullable=False),
        sa.Column("validation_status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["sandbox_runs.run_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["artifact_id"], ["analysis_artifacts.artifact_id"], ondelete="RESTRICT"),
        sa.CheckConstraint("validation_status IN ('validated', 'reviewed')", name="ck_analysis_citation_validation"),
        sa.UniqueConstraint("run_id", "artifact_id", "locator", "value_hash", name="uq_analysis_citation_value"),
    )
    op.create_index("ix_analysis_citation_project_run", "analysis_citations", ["project_id", "run_id"])

    op.create_table(
        "analysis_reproducibility_bundles",
        sa.Column("bundle_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_hash", sa.String(128), nullable=False),
        sa.Column("profile_hash", sa.String(128), nullable=False),
        sa.Column("research_context_hash", sa.String(128), nullable=True),
        sa.Column("plan_hash", sa.String(128), nullable=False),
        sa.Column("plan_decision_id", sa.Uuid(), nullable=False),
        sa.Column("action_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(128), nullable=False),
        sa.Column("model_route_audit_id", sa.String(255), nullable=False),
        sa.Column("image_digest", sa.String(512), nullable=False),
        sa.Column("package_manifest_hash", sa.String(128), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column("result_hash", sa.String(128), nullable=False),
        sa.Column("artifact_hashes_json", sa.JSON(), nullable=False),
        sa.Column("bundle_hash", sa.String(128), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["sandbox_runs.run_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("run_id", name="uq_reproducibility_bundle_run"),
    )
    op.create_index("ix_reproducibility_bundle_project_run", "analysis_reproducibility_bundles", ["project_id", "run_id"])


def downgrade() -> None:
    op.drop_index("ix_reproducibility_bundle_project_run", table_name="analysis_reproducibility_bundles")
    op.drop_table("analysis_reproducibility_bundles")
    op.drop_index("ix_analysis_citation_project_run", table_name="analysis_citations")
    op.drop_table("analysis_citations")
    op.drop_index("ix_result_review_project_run", table_name="analysis_result_reviews")
    op.drop_table("analysis_result_reviews")
    op.drop_index("ix_result_validation_project_run", table_name="analysis_result_validations")
    op.drop_table("analysis_result_validations")
    s5_run_statuses = (
        "pending_approval", "queued", "running", "completed_unvalidated", "failed",
        "timed_out", "policy_rejected", "cancelled",
    )
    op.drop_constraint("ck_sandbox_run_history_status", "sandbox_run_status_history", type_="check")
    op.create_check_constraint("ck_sandbox_run_history_status", "sandbox_run_status_history", f"to_status IN {s5_run_statuses}")
    op.drop_constraint("ck_sandbox_run_status", "sandbox_runs", type_="check")
    op.create_check_constraint("ck_sandbox_run_status", "sandbox_runs", f"status IN {s5_run_statuses}")
