"""Create immutable hypothesis, overlay, and adoption proposal records.

Revision ID: s0002
Revises: s0001
Create Date: 2026-08-15
"""

from alembic import op
import sqlalchemy as sa


revision = "s0002"
down_revision = "s0001"
branch_labels = None
depends_on = None


DRAFT_STATUSES = ("draft", "reviewed", "rejected", "superseded")
OVERLAY_STATUSES = ("draft", "assessed", "stale", "discarded")
OPERATION_TYPES = ("add_entity", "add_edge", "remove_edge", "replace_property")
ADOPTION_STATUSES = ("draft", "in_review", "approved", "rejected")


def upgrade() -> None:
    op.create_table(
        "sandbox_hypothesis_versions",
        sa.Column("hypothesis_version_id", sa.Uuid(), primary_key=True),
        sa.Column("hypothesis_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("supporting_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("counterevidence_refs", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("falsification_criteria", sa.JSON(), nullable=False),
        sa.Column("required_data", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("evidence_status", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["research_sandbox_sessions.session_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("hypothesis_id", "version", name="uq_sandbox_hypothesis_version"),
        sa.CheckConstraint(f"status IN {DRAFT_STATUSES}", name="ck_sandbox_hypothesis_status"),
    )
    op.create_index("ix_sandbox_hypothesis_project_session", "sandbox_hypothesis_versions", ["project_id", "session_id"])

    op.create_table(
        "sandbox_experiment_versions",
        sa.Column("experiment_version_id", sa.Uuid(), primary_key=True),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("hypothesis_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("independent_variables", sa.JSON(), nullable=False),
        sa.Column("dependent_variables", sa.JSON(), nullable=False),
        sa.Column("controls", sa.JSON(), nullable=False),
        sa.Column("data_requirements", sa.JSON(), nullable=False),
        sa.Column("method_candidates", sa.JSON(), nullable=False),
        sa.Column("evaluation_metrics", sa.JSON(), nullable=False),
        sa.Column("assumption_checks", sa.JSON(), nullable=False),
        sa.Column("stopping_criteria", sa.JSON(), nullable=False),
        sa.Column("risks", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["research_sandbox_sessions.session_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("experiment_id", "version", name="uq_sandbox_experiment_version"),
        sa.CheckConstraint(f"status IN {DRAFT_STATUSES}", name="ck_sandbox_experiment_status"),
    )
    op.create_index("ix_sandbox_experiment_project_session", "sandbox_experiment_versions", ["project_id", "session_id"])

    op.create_table(
        "sandbox_graph_overlays",
        sa.Column("overlay_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("base_graph_version_id", sa.String(255), nullable=False),
        sa.Column("shared_graph_version_id", sa.String(255), nullable=True),
        sa.Column("base_snapshot_hash", sa.String(128), nullable=False),
        sa.Column("operation_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["research_sandbox_sessions.session_id"], ondelete="CASCADE"),
        sa.CheckConstraint(f"status IN {OVERLAY_STATUSES}", name="ck_sandbox_overlay_status"),
        sa.UniqueConstraint("project_id", "overlay_id", name="uq_sandbox_overlay_project_id"),
    )
    op.create_index("ix_sandbox_overlay_project_session", "sandbox_graph_overlays", ["project_id", "session_id"])

    op.create_table(
        "sandbox_graph_overlay_operations",
        sa.Column("operation_id", sa.Uuid(), primary_key=True),
        sa.Column("overlay_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("entity_or_edge_type", sa.String(255), nullable=False),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("target_ref", sa.String(255), nullable=True),
        sa.Column("proposed_properties", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("hypothetical", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["overlay_id"], ["sandbox_graph_overlays.overlay_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("overlay_id", "sequence", name="uq_sandbox_overlay_operation_sequence"),
        sa.CheckConstraint(f"operation IN {OPERATION_TYPES}", name="ck_sandbox_overlay_operation"),
        sa.CheckConstraint("hypothetical = true", name="ck_sandbox_overlay_hypothetical"),
    )

    op.create_table(
        "sandbox_overlay_assessments",
        sa.Column("assessment_id", sa.Uuid(), primary_key=True),
        sa.Column("overlay_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("base_graph_version_id", sa.String(255), nullable=False),
        sa.Column("operation_hash", sa.String(128), nullable=False),
        sa.Column("newly_reachable_paths", sa.JSON(), nullable=False),
        sa.Column("conflicts", sa.JSON(), nullable=False),
        sa.Column("missing_evidence", sa.JSON(), nullable=False),
        sa.Column("compatibility_warnings", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["overlay_id"], ["sandbox_graph_overlays.overlay_id"], ondelete="CASCADE"),
        sa.CheckConstraint(f"status IN {OVERLAY_STATUSES}", name="ck_sandbox_assessment_status"),
    )
    op.create_index("ix_sandbox_assessment_overlay_hash", "sandbox_overlay_assessments", ["overlay_id", "operation_hash"])

    op.create_table(
        "sandbox_adoption_proposals",
        sa.Column("proposal_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["research_sandbox_sessions.session_id"], ondelete="CASCADE"),
        sa.CheckConstraint("source_type IN ('hypothesis', 'overlay_assessment')", name="ck_sandbox_adoption_source_type"),
        sa.CheckConstraint(f"status IN {ADOPTION_STATUSES}", name="ck_sandbox_adoption_status"),
    )
    op.create_index("ix_sandbox_adoption_project_session", "sandbox_adoption_proposals", ["project_id", "session_id"])

    op.create_table(
        "sandbox_adoption_decisions",
        sa.Column("decision_id", sa.Uuid(), primary_key=True),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("reviewer_id", sa.String(255), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["sandbox_adoption_proposals.proposal_id"], ondelete="CASCADE"),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_sandbox_adoption_decision"),
    )
    op.create_index("ix_sandbox_adoption_decision_proposal", "sandbox_adoption_decisions", ["proposal_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_sandbox_adoption_decision_proposal", table_name="sandbox_adoption_decisions")
    op.drop_table("sandbox_adoption_decisions")
    op.drop_index("ix_sandbox_adoption_project_session", table_name="sandbox_adoption_proposals")
    op.drop_table("sandbox_adoption_proposals")
    op.drop_index("ix_sandbox_assessment_overlay_hash", table_name="sandbox_overlay_assessments")
    op.drop_table("sandbox_overlay_assessments")
    op.drop_table("sandbox_graph_overlay_operations")
    op.drop_index("ix_sandbox_overlay_project_session", table_name="sandbox_graph_overlays")
    op.drop_table("sandbox_graph_overlays")
    op.drop_index("ix_sandbox_experiment_project_session", table_name="sandbox_experiment_versions")
    op.drop_table("sandbox_experiment_versions")
    op.drop_index("ix_sandbox_hypothesis_project_session", table_name="sandbox_hypothesis_versions")
    op.drop_table("sandbox_hypothesis_versions")
