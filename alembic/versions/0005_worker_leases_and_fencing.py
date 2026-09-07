"""Add worker ownership, heartbeat leases, and fencing to review jobs."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_worker_leases_and_fencing"
down_revision = "0004_two_parallel_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("review_jobs")}
    with op.batch_alter_table("review_jobs") as batch:
        if "worker_id" not in columns:
            batch.add_column(sa.Column("worker_id", sa.Text(), nullable=True))
        if "worker_heartbeat_at" not in columns:
            batch.add_column(sa.Column("worker_heartbeat_at", sa.Text(), nullable=True))
        if "lease_expires_at" not in columns:
            batch.add_column(sa.Column("lease_expires_at", sa.Text(), nullable=True))
        if "execution_fence" not in columns:
            batch.add_column(sa.Column("execution_fence", sa.Integer(), nullable=False, server_default=sa.text("0")))
    indexes = {index["name"] for index in inspector.get_indexes("review_jobs")}
    if "ix_review_jobs_active_lease" not in indexes:
        op.create_index("ix_review_jobs_active_lease", "review_jobs", ["status", "lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_review_jobs_active_lease", table_name="review_jobs")
    with op.batch_alter_table("review_jobs") as batch:
        batch.drop_column("execution_fence")
        batch.drop_column("lease_expires_at")
        batch.drop_column("worker_heartbeat_at")
        batch.drop_column("worker_id")
