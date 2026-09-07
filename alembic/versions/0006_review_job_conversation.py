"""Associate product review jobs with their originating conversation."""
from alembic import op
import sqlalchemy as sa
revision = "0006_review_job_conversation"
down_revision = "0005_worker_leases_and_fencing"
branch_labels = None
depends_on = None

def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("v2_project_review_jobs")}
    if "conversation_id" not in columns:
        op.add_column("v2_project_review_jobs", sa.Column("conversation_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_review_jobs_conversation", "v2_project_review_jobs", "v2_conversations",
        ["conversation_id"], ["conversation_id"], ondelete="SET NULL",
    )
    op.create_index("ix_review_jobs_conversation", "v2_project_review_jobs", ["conversation_id"])

def downgrade() -> None:
    op.drop_index("ix_review_jobs_conversation", table_name="v2_project_review_jobs")
    op.drop_constraint("fk_review_jobs_conversation", "v2_project_review_jobs", type_="foreignkey")
    op.drop_column("v2_project_review_jobs", "conversation_id")
