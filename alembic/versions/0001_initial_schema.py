"""initial postgres schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-05 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

from src.db.models import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.execute(
        """
        create or replace function prevent_parallel_project_research()
        returns trigger
        language plpgsql
        as $$
        begin
            perform pg_advisory_xact_lock(hashtextextended(new.project_id, 0));

            if new.status in ('queued', 'running', 'resuming') and exists (
                select 1
                from v2_project_review_jobs
                where project_id = new.project_id
                  and job_id <> new.job_id
                  and status in ('queued', 'running', 'resuming')
            ) then
                raise exception 'PROJECT_RESEARCH_BUSY'
                    using errcode = '23505',
                          constraint = 'v2_project_review_jobs_one_active_agent';
            end if;

            return new;
        end;
        $$;

        drop trigger if exists v2_project_review_jobs_one_active_agent
        on v2_project_review_jobs;

        create trigger v2_project_review_jobs_one_active_agent
        before insert or update of status on v2_project_review_jobs
        for each row execute function prevent_parallel_project_research();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(
        """
        drop trigger if exists v2_project_review_jobs_one_active_agent
        on v2_project_review_jobs;

        drop function if exists prevent_parallel_project_research();
        """
    )
    Base.metadata.drop_all(bind=bind)
