"""Allow up to two queued/running research jobs per project.

Revision ID: 0004_two_parallel_research
Revises: 0003_ai_interaction_logs
"""

from __future__ import annotations

from alembic import op

revision = "0004_two_parallel_research"
down_revision = "0003_ai_interaction_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create or replace function prevent_parallel_project_research()
        returns trigger
        language plpgsql
        as $$
        begin
            perform pg_advisory_xact_lock(hashtextextended(new.project_id, 0));

            if new.status in ('running', 'resuming') and (
                select count(*)
                from v2_project_review_jobs
                where project_id = new.project_id
                  and job_id <> new.job_id
                  and status in ('running', 'resuming')
            ) >= 2 then
                raise exception 'PROJECT_RESEARCH_QUEUE_LIMIT'
                    using errcode = '23505',
                          constraint = 'v2_project_review_jobs_two_active_limit';
            end if;

            return new;
        end;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        create or replace function prevent_parallel_project_research()
        returns trigger
        language plpgsql
        as $$
        begin
            perform pg_advisory_xact_lock(hashtextextended(new.project_id, 0));
            if new.status in ('queued', 'running', 'resuming') and exists (
                select 1 from v2_project_review_jobs
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
        """
    )
