"""Persist the requested language for AI-authored Sandbox outputs.

Revision ID: s0008
Revises: s0007
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa


revision = "s0008"
down_revision = "s0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_questions",
        sa.Column("output_language", sa.String(8), nullable=False, server_default="vi"),
    )
    op.create_check_constraint(
        "ck_analysis_question_output_language",
        "analysis_questions",
        "output_language IN ('vi', 'en')",
    )
    op.add_column(
        "analysis_plan_versions",
        sa.Column("output_language", sa.String(8), nullable=False, server_default="vi"),
    )
    op.create_check_constraint(
        "ck_analysis_plan_output_language",
        "analysis_plan_versions",
        "output_language IN ('vi', 'en')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_analysis_plan_output_language", "analysis_plan_versions", type_="check"
    )
    op.drop_column("analysis_plan_versions", "output_language")
    op.drop_constraint(
        "ck_analysis_question_output_language", "analysis_questions", type_="check"
    )
    op.drop_column("analysis_questions", "output_language")
