"""Track idempotent Sandbox adoption drafts in the core action ledger.

Revision ID: 0011_sandbox_adoption_sources
Revises: 0010_gap_quality_scores
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_sandbox_adoption_sources"
down_revision = "0010_gap_quality_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("v2_action_proposals")}
    if "external_source_system" not in columns:
        op.add_column(
            "v2_action_proposals",
            sa.Column("external_source_system", sa.Text(), nullable=True),
        )
    if "external_source_id" not in columns:
        op.add_column(
            "v2_action_proposals",
            sa.Column("external_source_id", sa.Text(), nullable=True),
        )

    indexes = {index["name"] for index in inspector.get_indexes("v2_action_proposals")}
    if "idx_v2_action_external_source" not in indexes:
        op.create_index(
            "idx_v2_action_external_source",
            "v2_action_proposals",
            ["project_id", "external_source_system", "external_source_id"],
            unique=True,
            postgresql_where=sa.text(
                "external_source_system IS NOT NULL AND external_source_id IS NOT NULL"
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("v2_action_proposals")}
    if "idx_v2_action_external_source" in indexes:
        op.drop_index("idx_v2_action_external_source", table_name="v2_action_proposals")
    columns = {column["name"] for column in inspector.get_columns("v2_action_proposals")}
    if "external_source_id" in columns:
        op.drop_column("v2_action_proposals", "external_source_id")
    if "external_source_system" in columns:
        op.drop_column("v2_action_proposals", "external_source_system")
