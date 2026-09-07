"""Complete durable code, nonce, and interpretation persistence.

Revision ID: s0007
Revises: s0006
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa


revision = "s0007"
down_revision = "s0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # S0004 carried an object-storage key but the current immutable domain
    # contract reads generated code synchronously from its repository.  Keep the
    # key for forward-compatible externalization and persist the sealed source
    # needed by workers after a process restart.
    op.add_column(
        "analysis_code_versions",
        sa.Column("source_code", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "analysis_code_versions",
        sa.Column("revision_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_analysis_code_revision_count",
        "analysis_code_versions",
        "revision_count BETWEEN 0 AND 1",
    )

    op.create_table(
        "sandbox_manifest_nonces",
        sa.Column("nonce", sa.String(255), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["sandbox_runs.run_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_sandbox_manifest_nonce_run", "sandbox_manifest_nonces", ["run_id"])

    op.create_table(
        "sandbox_service_auth_nonces",
        sa.Column("key_id", sa.String(255), primary_key=True),
        sa.Column("nonce", sa.String(255), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_sandbox_service_auth_nonce_expiry",
        "sandbox_service_auth_nonces",
        ["expires_at"],
    )

    op.create_table(
        "analysis_result_interpretations",
        sa.Column("interpretation_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.String(255), nullable=False, index=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("validation_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version", sa.String(128), nullable=False),
        sa.Column("narrative_json", sa.JSON(), nullable=False),
        sa.Column("numeric_claims_json", sa.JSON(), nullable=False),
        sa.Column("limitations_json", sa.JSON(), nullable=False),
        sa.Column("citation_ids_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["sandbox_runs.run_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["validation_id"], ["analysis_result_validations.validation_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "project_id", "run_id", name="uq_result_interpretation_project_run"
        ),
    )
    op.create_index(
        "ix_result_interpretation_project_run",
        "analysis_result_interpretations",
        ["project_id", "run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_result_interpretation_project_run", table_name="analysis_result_interpretations"
    )
    op.drop_table("analysis_result_interpretations")
    op.drop_index(
        "ix_sandbox_service_auth_nonce_expiry", table_name="sandbox_service_auth_nonces"
    )
    op.drop_table("sandbox_service_auth_nonces")
    op.drop_index("ix_sandbox_manifest_nonce_run", table_name="sandbox_manifest_nonces")
    op.drop_table("sandbox_manifest_nonces")
    op.drop_constraint(
        "ck_analysis_code_revision_count", "analysis_code_versions", type_="check"
    )
    op.drop_column("analysis_code_versions", "revision_count")
    op.drop_column("analysis_code_versions", "source_code")
