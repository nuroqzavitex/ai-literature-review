-- Keep the Supabase schema aligned with the V2 gap verification payload.
-- These columns are nullable so existing gap rows remain valid.
alter table v2_gaps
    add column if not exists confidence text,
    add column if not exists counter_search_query text,
    add column if not exists reviewer_rationale text,
    add column if not exists verification_status text,
    add column if not exists countersearch_report_version_id text;
