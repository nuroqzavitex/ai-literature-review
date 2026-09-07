"""revise v2 review job and report version keys

Revision ID: 0002_v2_review_keys
Revises: 0001_initial_schema
Create Date: 2026-08-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_v2_review_keys"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    primary_key = sa.inspect(op.get_bind()).get_pk_constraint("v2_project_review_jobs")
    if primary_key.get("constrained_columns") != ["job_id"]:
        op.execute("ALTER TABLE v2_project_review_jobs DROP CONSTRAINT IF EXISTS uq_v2_project_review_jobs_project_job")
        op.execute("ALTER TABLE v2_project_review_jobs DROP CONSTRAINT IF EXISTS v2_project_review_jobs_pkey")
        op.execute("ALTER TABLE v2_project_review_jobs ADD PRIMARY KEY (job_id)")

    op.execute("ALTER TABLE v2_report_versions DROP CONSTRAINT IF EXISTS uq_v2_report_versions_project_job")


def downgrade() -> None:
    op.execute("ALTER TABLE v2_report_versions ADD CONSTRAINT uq_v2_report_versions_project_job UNIQUE (project_id, job_id)")
    op.execute("ALTER TABLE v2_project_review_jobs DROP CONSTRAINT IF EXISTS v2_project_review_jobs_pkey")
    op.execute("ALTER TABLE v2_project_review_jobs ADD PRIMARY KEY (project_id)")
    op.execute(
        "ALTER TABLE v2_project_review_jobs ADD CONSTRAINT uq_v2_project_review_jobs_project_job UNIQUE (project_id, job_id)"
    )
