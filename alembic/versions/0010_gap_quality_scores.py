"""Persist independent quality scores and study metadata for research gaps."""

import sqlalchemy as sa

from alembic import op

revision = "0010_gap_quality_scores"
down_revision = "0009_default_max_results_15"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("evidence_score", sa.Integer()),
    ("novelty_score", sa.Integer()),
    ("feasibility_score", sa.Integer()),
    ("quality_score", sa.Integer()),
    ("suggested_method", sa.Text()),
    ("falsification_condition", sa.Text()),
    ("source_type", sa.Text()),
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
