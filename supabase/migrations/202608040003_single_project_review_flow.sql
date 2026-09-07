-- A project represents one continuous literature-review workflow. Report
-- revisions remain attached to that workflow instead of starting a second job.
--
-- The advisory lock makes the check safe when two browser tabs submit at the
-- same time. Existing duplicate rows are deliberately left untouched so this
-- migration never destroys user data; it only prevents new duplicates.
create or replace function prevent_multiple_project_review_flows()
returns trigger
language plpgsql
as $$
begin
    perform pg_advisory_xact_lock(hashtextextended(new.project_id, 0));

    if exists (
        select 1
        from v2_project_review_jobs
        where project_id = new.project_id
    ) then
        raise exception 'PROJECT_REVIEW_EXISTS'
            using errcode = '23505',
                  constraint = 'v2_project_review_jobs_single_flow';
    end if;

    return new;
end;
$$;

drop trigger if exists v2_project_review_jobs_single_flow
on v2_project_review_jobs;

create trigger v2_project_review_jobs_single_flow
before insert on v2_project_review_jobs
for each row execute function prevent_multiple_project_review_flows();
