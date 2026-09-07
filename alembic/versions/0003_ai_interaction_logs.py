"""add ai interaction logs table

Revision ID: 0003_ai_interaction_logs
Revises: 0002_v2_review_keys
Create Date: 2026-08-07 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_ai_interaction_logs"
down_revision = "0002_v2_review_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 creates Base.metadata, including this table in fresh installations.
    # Keep this revision safe for both fresh and upgraded databases.
    if sa.inspect(op.get_bind()).has_table("ai_interaction_logs"):
        return
    op.create_table(
        "ai_interaction_logs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("node_name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("prompt_preview", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("response_preview", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("prompt_payload", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("response_payload", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("tokens_prompt", sa.Integer()),
        sa.Column("tokens_completion", sa.Integer()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("error_type", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_ai_interaction_logs_job_created", "ai_interaction_logs", ["job_id", "created_at"])
    op.create_index("ix_ai_interaction_logs_job_event", "ai_interaction_logs", ["job_id", "event_type"])


def downgrade() -> None:
    op.drop_index("ix_ai_interaction_logs_job_event", table_name="ai_interaction_logs")
    op.drop_index("ix_ai_interaction_logs_job_created", table_name="ai_interaction_logs")
    op.drop_table("ai_interaction_logs")
