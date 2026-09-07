-- Projects are broad workspaces. Each project may contain many research
-- threads, while only one thread may actively consume an agent at a time.

drop trigger if exists v2_project_review_jobs_single_flow
on v2_project_review_jobs;

drop trigger if exists v2_project_review_jobs_one_active_agent
on v2_project_review_jobs;

drop function if exists prevent_multiple_project_review_flows();

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

create trigger v2_project_review_jobs_one_active_agent
before insert or update of status on v2_project_review_jobs
for each row execute function prevent_parallel_project_research();

-- Report version numbers are scoped to a research thread (job), not to the
-- entire project. A resumed reviewer revision can therefore create v2, v3...
-- on the same thread, while another thread starts independently at v1.
alter table v2_report_versions
    drop constraint if exists v2_report_versions_project_id_job_id_key;
alter table v2_report_versions
    drop constraint if exists v2_report_versions_project_id_version_number_key;

with ranked as (
    select report_version_id,
           row_number() over (
               partition by project_id, job_id
               order by created_at, report_version_id
           ) as thread_version_number
    from v2_report_versions
    where job_id is not null
)
update v2_report_versions as versions
set version_number = ranked.thread_version_number
from ranked
where versions.report_version_id = ranked.report_version_id
  and versions.version_number <> ranked.thread_version_number;

create unique index if not exists v2_report_versions_thread_version_key
    on v2_report_versions(project_id, job_id, version_number)
    where job_id is not null;
