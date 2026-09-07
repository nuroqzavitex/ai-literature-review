from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy import text as sa_text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Users(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint("role IN ('researcher', 'reviewer')", name="ck_users_role"),)


class ReviewJob(Base):
    __tablename__ = "review_jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.id"), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    max_results: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    current_node: Mapped[str] = mapped_column(Text, nullable=False)
    papers_found: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    progress_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'{}'"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(Text)
    resume_claimed_at: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(Text)
    worker_heartbeat_at: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[str | None] = mapped_column(Text)
    execution_fence: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))


class ReviewReport(Base):
    __tablename__ = "review_reports"

    job_id: Mapped[str] = mapped_column(Text, ForeignKey("review_jobs.id"), primary_key=True)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    hitl_approved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    reviewer_notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("''"))
    reviewed_by: Mapped[str | None] = mapped_column(Text, ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_at: Mapped[str | None] = mapped_column(Text)


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    job_id: Mapped[str] = mapped_column(Text, ForeignKey("review_jobs.id"), primary_key=True)
    reviewer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    claim_id: Mapped[str] = mapped_column(Text, primary_key=True)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("''"))
    reviewed_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint("verdict IN ('supported', 'unsupported')", name="ck_review_decisions_verdict"),)


class ReferenceCheck(Base):
    __tablename__ = "reference_checks"

    job_id: Mapped[str] = mapped_column(Text, ForeignKey("review_jobs.id"), primary_key=True)
    reviewer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    paper_id: Mapped[str] = mapped_column(Text, primary_key=True)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("''"))
    checked_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint("verdict IN ('valid', 'invalid')", name="ck_reference_checks_verdict"),)


class ReportReview(Base):
    __tablename__ = "report_reviews"

    job_id: Mapped[str] = mapped_column(Text, ForeignKey("review_jobs.id"), primary_key=True)
    reviewer_id: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("''"))
    reviewed_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint("decision IN ('approve', 'request_changes')", name="ck_report_reviews_decision"),)


class EvaluationRecord(Base):
    __tablename__ = "evaluation_records"

    job_id: Mapped[str] = mapped_column(Text, ForeignKey("review_jobs.id"), primary_key=True)
    evaluator_id: Mapped[str] = mapped_column(Text, nullable=False)
    manual_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    mvp_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    usefulness_score: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    evaluated_at: Mapped[str] = mapped_column(Text, nullable=False)


class V2Actor(Base):
    __tablename__ = "v2_actors"

    actor_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("''"))
    actor_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'researcher'"))
    email: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (CheckConstraint("actor_type IN ('researcher', 'reviewer', 'admin')", name="ck_v2_actors_type"),)


class V2Session(Base):
    __tablename__ = "v2_sessions"

    session_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    actor_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_actors.actor_id"), nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class V2Project(Base):
    __tablename__ = "v2_projects"

    project_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("''"))
    owner_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_actors.actor_id"), nullable=False)
    active_report_version_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class V2ProjectMembership(Base):
    __tablename__ = "v2_project_memberships"

    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), primary_key=True)
    actor_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_actors.actor_id"), primary_key=True)
    project_role: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("project_role IN ('owner', 'researcher', 'reviewer')", name="ck_v2_memberships_role"),
    )


class V2ProjectReviewJob(Base):
    __tablename__ = "v2_project_review_jobs"

    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("v2_conversations.conversation_id"), nullable=True
    )
    requested_by: Mapped[str] = mapped_column(Text, ForeignKey("v2_actors.actor_id"), nullable=False)
    parent_report_version_id: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("''"))
    max_results: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("20"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'queued'"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class V2ResearchPlan(Base):
    __tablename__ = "v2_research_plans"

    plan_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(Text, ForeignKey("v2_conversations.conversation_id"))
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(Text, nullable=False)
    sub_queries_json: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, nullable=False)
    selection_criteria_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, ForeignKey("v2_actors.actor_id"), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(Text, ForeignKey("v2_actors.actor_id"))
    approved_at: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(Text, ForeignKey("v2_project_review_jobs.job_id"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('proposed', 'approved', 'cancelled')", name="ck_v2_research_plans_status"),
    )


class V2ReportVersion(Base):
    __tablename__ = "v2_report_versions"

    report_version_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    job_id: Mapped[str | None] = mapped_column(Text)
    parent_report_version_id: Mapped[str | None] = mapped_column(Text)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    corpus_hash: Mapped[str] = mapped_column(Text, nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, ForeignKey("v2_actors.actor_id"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "version_number", name="uq_v2_report_versions_project_version"),)


class V2ProjectInvitation(Base):
    __tablename__ = "v2_project_invitations"

    invitation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    job_id: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    invited_by: Mapped[str] = mapped_column(Text, ForeignKey("v2_actors.actor_id"), nullable=False)
    accepted_by: Mapped[str | None] = mapped_column(Text, ForeignKey("v2_actors.actor_id"))
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    responded_at: Mapped[str | None] = mapped_column(Text)
    email_delivery_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'not_configured'"))
    email_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sa_text("0"))
    last_email_attempt_at: Mapped[str | None] = mapped_column(Text)
    email_sent_at: Mapped[str | None] = mapped_column(Text)
    email_error: Mapped[str | None] = mapped_column(Text)
    resend_email_id: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("project_id", "job_id", "email", name="uq_v2_project_invitation_email"),)


class V2ReviewAssignment(Base):
    __tablename__ = "v2_review_assignments"

    assignment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    job_id: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_actors.actor_id"), nullable=False)
    invitation_id: Mapped[str | None] = mapped_column(Text, ForeignKey("v2_project_invitations.invitation_id"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_at: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("status IN ('assigned', 'submitted', 'revoked')", name="ck_v2_review_assignments_status"),
        UniqueConstraint("job_id", "reviewer_id", name="uq_v2_review_assignments_job_reviewer"),
    )


class V2ReviewSubmission(Base):
    __tablename__ = "v2_review_submissions"

    submission_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    job_id: Mapped[str] = mapped_column(Text, nullable=False)
    report_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("v2_report_versions.report_version_id"), nullable=False
    )
    reviewer_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_actors.actor_id"), nullable=False)
    review_type: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("''"))
    decisions_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'[]'"))
    reference_checks_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'[]'"))
    submitted_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("review_type IN ('self_review', 'external_review')", name="ck_v2_review_submissions_type"),
        CheckConstraint("decision IN ('approve', 'request_changes')", name="ck_v2_review_submissions_decision"),
        UniqueConstraint(
            "job_id", "reviewer_id", "report_version_id", name="uq_v2_review_submissions_job_reviewer_report"
        ),
    )


class V2Conversation(Base):
    __tablename__ = "v2_conversations"

    conversation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    created_by: Mapped[str] = mapped_column(Text, ForeignKey("v2_actors.actor_id"), nullable=False)
    active_report_version_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'New conversation'"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class V2Message(Base):
    __tablename__ = "v2_messages"

    message_id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_conversations.conversation_id"), nullable=False)
    client_message_id: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    report_version_id: Mapped[str | None] = mapped_column(Text)
    content_scope: Mapped[str | None] = mapped_column(Text)
    limitations_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'[]'"))
    context_artifact_ids_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'[]'"))
    memory_ids_used_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'[]'"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_v2_messages_role"),
        UniqueConstraint("conversation_id", "client_message_id", name="uq_v2_messages_client_message"),
    )


class V2MessageCitation(Base):
    __tablename__ = "v2_message_citations"

    citation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    message_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_messages.message_id"), nullable=False)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    report_version_id: Mapped[str] = mapped_column(Text, nullable=False)
    paper_id: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_id: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    valid: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class V2Memory(Base):
    __tablename__ = "v2_memories"

    memory_id: Mapped[str] = mapped_column(Text, primary_key=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(Text, nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'[]'"))
    report_version_id: Mapped[str | None] = mapped_column(Text)
    dependency_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(Text)
    supersedes_memory_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint("scope IN ('session', 'project')", name="ck_v2_memories_scope"),)


class V2ActionProposal(Base):
    __tablename__ = "v2_action_proposals"

    action_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    base_report_version_id: Mapped[str | None] = mapped_column(Text)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_feedback_id: Mapped[str | None] = mapped_column(Text)
    external_source_system: Mapped[str | None] = mapped_column(Text)
    external_source_id: Mapped[str | None] = mapped_column(Text)
    acceptance_criteria_json: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_impact_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_by: Mapped[str] = mapped_column(Text, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    approval_payload_hash: Mapped[str | None] = mapped_column(Text)
    executed_job_id: Mapped[str | None] = mapped_column(Text)
    result_report_version_id: Mapped[str | None] = mapped_column(Text)
    result_artifact_ids_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'[]'"))
    failure_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(Text)


class V2Gap(Base):
    __tablename__ = "v2_gaps"

    gap_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_projects.project_id"), nullable=False)
    report_version_id: Mapped[str] = mapped_column(Text, nullable=False)
    gap_type: Mapped[str] = mapped_column(Text, nullable=False)
    scoped_statement: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    corpus_size: Mapped[int] = mapped_column(Integer, nullable=False)
    present_count: Mapped[int] = mapped_column(Integer, nullable=False)
    not_reported_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unknown_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_scope: Mapped[str] = mapped_column(Text, nullable=False)
    content_scope: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_json: Mapped[str] = mapped_column(Text, nullable=False)
    counterevidence_paper_ids_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sa_text("'[]'"))
    confidence: Mapped[str | None] = mapped_column(Text)
    counter_search_query: Mapped[str | None] = mapped_column(Text)
    reviewer_rationale: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str | None] = mapped_column(Text)
    countersearch_report_version_id: Mapped[str | None] = mapped_column(Text)
    evidence_score: Mapped[int | None] = mapped_column(Integer)
    novelty_score: Mapped[int | None] = mapped_column(Integer)
    feasibility_score: Mapped[int | None] = mapped_column(Integer)
    quality_score: Mapped[int | None] = mapped_column(Integer)
    suggested_method: Mapped[str | None] = mapped_column(Text)
    falsification_condition: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "report_version_id", "gap_id", name="uq_v2_gaps_project_report_gap"),
    )


class V2GapDecision(Base):
    __tablename__ = "v2_gap_decisions"

    decision_id: Mapped[str] = mapped_column(Text, primary_key=True)
    gap_id: Mapped[str] = mapped_column(Text, ForeignKey("v2_gaps.gap_id"), nullable=False)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    report_version_id: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    revised_statement: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_at: Mapped[str] = mapped_column(Text, nullable=False)


class V2ReviewerFeedback(Base):
    __tablename__ = "v2_reviewer_feedback"

    feedback_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    report_version_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_decision_id: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    revised_text: Mapped[str | None] = mapped_column(Text)
    requested_action: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    action_id: Mapped[str | None] = mapped_column(Text)
    memory_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged_at: Mapped[str | None] = mapped_column(Text)


class V2AuditEvent(Base):
    __tablename__ = "v2_audit_events"

    audit_id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    base_version_id: Mapped[str | None] = mapped_column(Text)
    result_version_id: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class V2Event(Base):
    __tablename__ = "v2_events"

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str | None] = mapped_column(Text)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("project_id", "sequence", name="uq_v2_events_project_sequence"),)


Index(
    "idx_v2_actors_email",
    func.lower(V2Actor.email),
    unique=True,
    postgresql_where=V2Actor.email.is_not(None) & V2Actor.deleted_at.is_(None),
)
Index("idx_v2_memberships_actor", V2ProjectMembership.actor_id)
Index("idx_v2_reviews_project", V2ProjectReviewJob.project_id, V2ProjectReviewJob.created_at.desc())
Index("idx_v2_assignments_reviewer", V2ReviewAssignment.reviewer_id, V2ReviewAssignment.status)
Index("idx_v2_messages_conversation", V2Message.conversation_id, V2Message.created_at)
Index(
    "idx_v2_action_idempotency",
    V2ActionProposal.project_id,
    V2ActionProposal.idempotency_key,
    unique=True,
    postgresql_where=V2ActionProposal.idempotency_key.is_not(None),
)
Index(
    "idx_v2_action_external_source",
    V2ActionProposal.project_id,
    V2ActionProposal.external_source_system,
    V2ActionProposal.external_source_id,
    unique=True,
    postgresql_where=(
        V2ActionProposal.external_source_system.is_not(None) & V2ActionProposal.external_source_id.is_not(None)
    ),
)
