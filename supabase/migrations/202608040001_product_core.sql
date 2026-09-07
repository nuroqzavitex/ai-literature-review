-- LitReview product data for Supabase PostgreSQL.
-- Clerk remains the identity provider; this schema stores only the application
-- profile and the Clerk subject used by project authorization.

create table if not exists v2_actors (
    actor_id text primary key,
    display_name text not null default '',
    actor_type text not null default 'researcher'
        check (actor_type in ('researcher', 'reviewer', 'admin')),
    email text,
    image_url text,
    deleted_at text,
    created_at text not null,
    updated_at text not null
);

alter table v2_actors add column if not exists email text;
alter table v2_actors add column if not exists image_url text;
alter table v2_actors add column if not exists deleted_at text;
alter table v2_actors add column if not exists updated_at text not null default '';

create unique index if not exists idx_v2_actors_email
    on v2_actors(lower(email)) where email is not null and deleted_at is null;

create table if not exists v2_sessions (
    session_hash text primary key,
    actor_id text not null references v2_actors(actor_id),
    expires_at text not null,
    revoked_at text,
    created_at text not null
);

create table if not exists v2_projects (
    project_id text primary key,
    name text not null,
    description text not null default '',
    owner_id text not null references v2_actors(actor_id),
    active_report_version_id text,
    created_at text not null,
    updated_at text not null
);

create table if not exists v2_project_memberships (
    project_id text not null references v2_projects(project_id),
    actor_id text not null references v2_actors(actor_id),
    project_role text not null check (project_role in ('owner','researcher','reviewer')),
    created_at text not null,
    primary key(project_id, actor_id)
);

create table if not exists v2_project_review_jobs (
    project_id text not null references v2_projects(project_id),
    job_id text not null unique,
    requested_by text not null references v2_actors(actor_id),
    parent_report_version_id text,
    purpose text not null,
    topic text not null default '',
    max_results integer not null default 10,
    status text not null default 'queued',
    created_at text not null,
    primary key(project_id, job_id)
);

alter table v2_project_review_jobs add column if not exists topic text not null default '';
alter table v2_project_review_jobs add column if not exists max_results integer not null default 10;
alter table v2_project_review_jobs add column if not exists status text not null default 'queued';

create table if not exists v2_report_versions (
    report_version_id text primary key,
    project_id text not null references v2_projects(project_id),
    job_id text,
    parent_report_version_id text,
    version_number integer not null,
    corpus_hash text not null,
    report_json text not null,
    change_reason text not null,
    created_by text not null references v2_actors(actor_id),
    created_at text not null,
    unique(project_id, version_number),
    unique(project_id, job_id)
);

create table if not exists v2_project_invitations (
    invitation_id text primary key,
    project_id text not null references v2_projects(project_id),
    job_id text not null,
    email text not null,
    token_hash text not null unique,
    status text not null check (status in ('pending','accepted','declined','expired','revoked')),
    invited_by text not null references v2_actors(actor_id),
    accepted_by text references v2_actors(actor_id),
    expires_at text not null,
    created_at text not null,
    responded_at text,
    email_delivery_status text not null default 'not_configured',
    email_attempts integer not null default 0,
    last_email_attempt_at text,
    email_sent_at text,
    email_error text,
    resend_email_id text,
    unique(project_id, job_id, email)
);

alter table v2_project_invitations add column if not exists email_delivery_status text not null default 'not_configured';
alter table v2_project_invitations add column if not exists email_attempts integer not null default 0;
alter table v2_project_invitations add column if not exists last_email_attempt_at text;
alter table v2_project_invitations add column if not exists email_sent_at text;
alter table v2_project_invitations add column if not exists email_error text;
alter table v2_project_invitations add column if not exists resend_email_id text;

create table if not exists v2_review_assignments (
    assignment_id text primary key,
    project_id text not null references v2_projects(project_id),
    job_id text not null,
    reviewer_id text not null references v2_actors(actor_id),
    invitation_id text references v2_project_invitations(invitation_id),
    status text not null check (status in ('assigned','submitted','revoked')),
    assigned_at text not null,
    submitted_at text,
    unique(job_id, reviewer_id)
);

create table if not exists v2_review_submissions (
    submission_id text primary key,
    project_id text not null references v2_projects(project_id),
    job_id text not null,
    report_version_id text not null references v2_report_versions(report_version_id),
    reviewer_id text not null references v2_actors(actor_id),
    review_type text not null check (review_type in ('self_review','external_review')),
    decision text not null check (decision in ('approve','request_changes')),
    note text not null default '',
    decisions_json text not null default '[]',
    reference_checks_json text not null default '[]',
    submitted_at text not null,
    unique(job_id, reviewer_id, report_version_id)
);

alter table v2_review_submissions add column if not exists decisions_json text not null default '[]';
alter table v2_review_submissions add column if not exists reference_checks_json text not null default '[]';

create table if not exists v2_conversations (
    conversation_id text primary key,
    project_id text not null references v2_projects(project_id),
    created_by text not null references v2_actors(actor_id),
    active_report_version_id text,
    title text not null default 'New conversation',
    created_at text not null,
    updated_at text not null
);

alter table v2_conversations add column if not exists title text not null default 'New conversation';

create table if not exists v2_messages (
    message_id text primary key,
    conversation_id text not null references v2_conversations(conversation_id),
    client_message_id text,
    role text not null check(role in ('user','assistant')),
    message_type text not null,
    text text not null,
    report_version_id text,
    content_scope text,
    limitations_json text not null default '[]',
    context_artifact_ids_json text not null default '[]',
    memory_ids_used_json text not null default '[]',
    created_at text not null,
    unique(conversation_id, client_message_id)
);

create table if not exists v2_message_citations (
    citation_id text primary key,
    message_id text not null references v2_messages(message_id),
    project_id text not null,
    report_version_id text not null,
    paper_id text not null,
    evidence_id text,
    quote text not null,
    source_url text not null,
    valid integer not null,
    created_at text not null
);

create table if not exists v2_memories (
    memory_id text primary key,
    scope text not null check(scope in ('session','project')),
    project_id text not null references v2_projects(project_id),
    conversation_id text,
    memory_type text not null,
    content_json text not null,
    evidence_ids_json text not null default '[]',
    report_version_id text,
    dependency_hash text,
    status text not null,
    created_by text not null,
    confirmed_by text,
    supersedes_memory_id text,
    created_at text not null,
    expires_at text,
    deleted_at text
);

create table if not exists v2_action_proposals (
    action_id text primary key,
    project_id text not null references v2_projects(project_id),
    conversation_id text,
    base_report_version_id text,
    action_type text not null,
    parameters_json text not null,
    reason text not null,
    source_feedback_id text,
    acceptance_criteria_json text not null,
    estimated_impact_json text not null,
    status text not null,
    proposed_by text not null,
    approved_by text,
    approved_at text,
    idempotency_key text,
    approval_payload_hash text,
    executed_job_id text,
    result_report_version_id text,
    result_artifact_ids_json text not null default '[]',
    failure_code text,
    created_at text not null,
    completed_at text
);

create unique index if not exists idx_v2_action_idempotency
    on v2_action_proposals(project_id, idempotency_key)
    where idempotency_key is not null;

create table if not exists v2_gaps (
    gap_id text primary key,
    project_id text not null references v2_projects(project_id),
    report_version_id text not null,
    gap_type text not null,
    scoped_statement text not null,
    status text not null,
    corpus_size integer not null,
    present_count integer not null,
    not_reported_count integer not null,
    unknown_count integer not null,
    source_scope text not null,
    content_scope text not null,
    coverage_json text not null,
    counterevidence_paper_ids_json text not null default '[]',
    created_at text not null,
    unique(project_id, report_version_id, gap_id)
);

create table if not exists v2_gap_decisions (
    decision_id text primary key,
    gap_id text not null references v2_gaps(gap_id),
    project_id text not null,
    report_version_id text not null,
    reviewer_id text not null,
    verdict text not null,
    revised_statement text,
    note text not null,
    reviewed_at text not null
);

create table if not exists v2_reviewer_feedback (
    feedback_id text primary key,
    project_id text not null,
    report_version_id text not null,
    source_decision_id text not null,
    target_type text not null,
    target_id text not null,
    verdict text not null,
    note text not null,
    revised_text text,
    requested_action text not null,
    status text not null,
    action_id text,
    memory_id text,
    created_at text not null,
    acknowledged_at text
);

create table if not exists v2_audit_events (
    audit_id text primary key,
    project_id text not null,
    actor_id text not null,
    event_type text not null,
    entity_type text not null,
    entity_id text not null,
    base_version_id text,
    result_version_id text,
    correlation_id text not null,
    metadata_json text not null,
    created_at text not null
);

create table if not exists v2_events (
    event_id text primary key,
    sequence integer not null,
    project_id text not null,
    conversation_id text,
    event_type text not null,
    entity_id text,
    data_json text not null,
    created_at text not null,
    unique(project_id, sequence)
);

create index if not exists idx_v2_memberships_actor on v2_project_memberships(actor_id);
create index if not exists idx_v2_reviews_project on v2_project_review_jobs(project_id, created_at desc);
create index if not exists idx_v2_assignments_reviewer on v2_review_assignments(reviewer_id, status);
create index if not exists idx_v2_messages_conversation on v2_messages(conversation_id, created_at);

-- The browser never connects to product tables directly. All product access
-- passes through FastAPI's Clerk verification and project authorization.
-- Restrict Supabase Data API roles so an accidentally exposed publishable key
-- cannot bypass those policies; the backend database role remains unaffected.
do $$
declare table_name text;
begin
  foreach table_name in array array[
    'v2_actors','v2_sessions','v2_projects','v2_project_memberships',
    'v2_project_review_jobs','v2_report_versions','v2_project_invitations',
    'v2_review_assignments','v2_review_submissions','v2_conversations',
    'v2_messages','v2_message_citations','v2_memories','v2_action_proposals',
    'v2_gaps','v2_gap_decisions','v2_reviewer_feedback','v2_audit_events','v2_events'
  ] loop
    execute format('alter table %I enable row level security', table_name);
  end loop;
end $$;
