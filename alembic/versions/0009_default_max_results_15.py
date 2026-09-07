"""Use 15 papers as the default review corpus size."""

from __future__ import annotations

from alembic import op

revision = "0009_default_max_results_15"
down_revision = "0008_gap_verification_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE v2_project_review_jobs ALTER COLUMN max_results SET DEFAULT 15")


def downgrade() -> None:
    op.execute("ALTER TABLE v2_project_review_jobs ALTER COLUMN max_results SET DEFAULT 10")
