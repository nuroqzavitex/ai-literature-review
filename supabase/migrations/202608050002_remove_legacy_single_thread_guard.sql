-- Final compatibility cleanup for databases that previously enforced exactly
-- one research thread per project. The old trigger may have been installed
-- under a different name, so remove it by its trigger function as well as by
-- the original known name.

do $$
declare
    legacy_trigger record;
begin
    for legacy_trigger in
        select trigger_row.tgname
        from pg_trigger as trigger_row
        join pg_proc as trigger_function
          on trigger_function.oid = trigger_row.tgfoid
        where trigger_row.tgrelid = 'v2_project_review_jobs'::regclass
          and not trigger_row.tgisinternal
          and trigger_function.proname = 'prevent_multiple_project_review_flows'
    loop
        execute format(
            'drop trigger if exists %I on v2_project_review_jobs',
            legacy_trigger.tgname
        );
    end loop;
end;
$$;

drop trigger if exists v2_project_review_jobs_single_flow
on v2_project_review_jobs;

drop function if exists prevent_multiple_project_review_flows();
