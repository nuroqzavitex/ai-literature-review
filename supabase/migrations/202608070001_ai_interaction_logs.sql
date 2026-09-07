-- Structured AI interaction traces.

create table if not exists ai_interaction_logs (
    id text primary key,
    job_id text not null,
    trace_id text not null,
    node_name text not null,
    provider text not null,
    model text not null,
    event_type text not null,
    attempt integer not null default 1,
    status text not null,
    prompt_preview text not null default '',
    response_preview text not null default '',
    prompt_payload text not null default '',
    response_payload text not null default '',
    tokens_prompt integer,
    tokens_completion integer,
    latency_ms integer,
    error_type text,
    error_message text,
    created_at text not null
);

create index if not exists ix_ai_interaction_logs_job_created
    on ai_interaction_logs(job_id, created_at);

create index if not exists ix_ai_interaction_logs_job_event
    on ai_interaction_logs(job_id, event_type);
