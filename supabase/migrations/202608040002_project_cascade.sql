-- Delete an entire project graph inside PostgreSQL. Actor relationships are
-- intentionally not cascaded because Clerk users are soft-deleted and may own
-- or participate in more than one project.

alter table v2_project_memberships
    drop constraint if exists v2_project_memberships_project_id_fkey;
alter table v2_project_memberships
    add constraint v2_project_memberships_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_project_review_jobs
    drop constraint if exists v2_project_review_jobs_project_id_fkey;
alter table v2_project_review_jobs
    add constraint v2_project_review_jobs_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_report_versions
    drop constraint if exists v2_report_versions_project_id_fkey;
alter table v2_report_versions
    add constraint v2_report_versions_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_project_invitations
    drop constraint if exists v2_project_invitations_project_id_fkey;
alter table v2_project_invitations
    add constraint v2_project_invitations_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_review_assignments
    drop constraint if exists v2_review_assignments_project_id_fkey;
alter table v2_review_assignments
    add constraint v2_review_assignments_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_review_submissions
    drop constraint if exists v2_review_submissions_project_id_fkey;
alter table v2_review_submissions
    add constraint v2_review_submissions_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_conversations
    drop constraint if exists v2_conversations_project_id_fkey;
alter table v2_conversations
    add constraint v2_conversations_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_messages
    drop constraint if exists v2_messages_conversation_id_fkey;
alter table v2_messages
    add constraint v2_messages_conversation_id_fkey
    foreign key (conversation_id) references v2_conversations(conversation_id) on delete cascade;

alter table v2_message_citations
    drop constraint if exists v2_message_citations_message_id_fkey;
alter table v2_message_citations
    add constraint v2_message_citations_message_id_fkey
    foreign key (message_id) references v2_messages(message_id) on delete cascade;
alter table v2_message_citations
    drop constraint if exists v2_message_citations_project_id_fkey;
alter table v2_message_citations
    add constraint v2_message_citations_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_memories
    drop constraint if exists v2_memories_project_id_fkey;
alter table v2_memories
    add constraint v2_memories_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_action_proposals
    drop constraint if exists v2_action_proposals_project_id_fkey;
alter table v2_action_proposals
    add constraint v2_action_proposals_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_gaps
    drop constraint if exists v2_gaps_project_id_fkey;
alter table v2_gaps
    add constraint v2_gaps_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_gap_decisions
    drop constraint if exists v2_gap_decisions_gap_id_fkey;
alter table v2_gap_decisions
    add constraint v2_gap_decisions_gap_id_fkey
    foreign key (gap_id) references v2_gaps(gap_id) on delete cascade;
alter table v2_gap_decisions
    drop constraint if exists v2_gap_decisions_project_id_fkey;
alter table v2_gap_decisions
    add constraint v2_gap_decisions_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_reviewer_feedback
    drop constraint if exists v2_reviewer_feedback_project_id_fkey;
alter table v2_reviewer_feedback
    add constraint v2_reviewer_feedback_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_audit_events
    drop constraint if exists v2_audit_events_project_id_fkey;
alter table v2_audit_events
    add constraint v2_audit_events_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;

alter table v2_events
    drop constraint if exists v2_events_project_id_fkey;
alter table v2_events
    add constraint v2_events_project_id_fkey
    foreign key (project_id) references v2_projects(project_id) on delete cascade;
