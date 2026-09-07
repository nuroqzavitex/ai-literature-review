"""Persist proposed research plans before a search job is created."""

import sqlalchemy as sa

from alembic import op

revision = "0007_research_plans"
down_revision = "0006_review_job_conversation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("v2_research_plans"):
        return
    op.create_table(
        "v2_research_plans",
        sa.Column("plan_id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), sa.ForeignKey("v2_projects.project_id"), nullable=False),
        sa.Column("conversation_id", sa.Text(), sa.ForeignKey("v2_conversations.conversation_id")),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("normalized_question", sa.Text(), nullable=False),
        sa.Column("sub_queries_json", sa.Text(), nullable=False),
        sa.Column("sources_json", sa.Text(), nullable=False),
        sa.Column("selection_criteria_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), sa.ForeignKey("v2_actors.actor_id"), nullable=False),
        sa.Column("approved_by", sa.Text(), sa.ForeignKey("v2_actors.actor_id")),
        sa.Column("approved_at", sa.Text()),
        sa.Column("job_id", sa.Text(), sa.ForeignKey("v2_project_review_jobs.job_id")),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint("status IN ('proposed', 'approved', 'cancelled')", name="ck_v2_research_plans_status"),
    )
    op.create_index("ix_v2_research_plans_project_status", "v2_research_plans", ["project_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_v2_research_plans_project_status", table_name="v2_research_plans")
    op.drop_table("v2_research_plans")
