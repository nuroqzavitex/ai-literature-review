"""Persist the evidence needed to verify a scoped research-gap candidate."""

import sqlalchemy as sa

from alembic import op


revision = "0008_gap_verification_metadata"
down_revision = "0007_research_plans"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("confidence", sa.Text()),
    ("counter_search_query", sa.Text()),
    ("reviewer_rationale", sa.Text()),
    ("verification_status", sa.Text()),
    ("countersearch_report_version_id", sa.Text()),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("v2_gaps"):
        return
    existing = {column["name"] for column in inspector.get_columns("v2_gaps")}
    for name, column_type in _COLUMNS:
        if name not in existing:
            op.add_column("v2_gaps", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("v2_gaps"):
        return
    existing = {column["name"] for column in inspector.get_columns("v2_gaps")}
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("v2_gaps", name)
