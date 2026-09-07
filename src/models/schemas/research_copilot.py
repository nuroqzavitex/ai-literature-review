from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ProjectRole = Literal["owner", "researcher", "reviewer"]
MemoryType = Literal[
    "research_scope",
    "hypothesis",
    "decision",
    "reviewer_feedback",
    "open_question",
    "task",
    "conversation_summary",
]
ActionType = Literal[
    "refine_scope",
    "search_more",
    "add_paper",
    "exclude_paper",
    "rerun_grounding",
    "countersearch",
    "revise_claim",
    "narrow_claim",
    "discard_claim",
    "adopt_sandbox_proposal",
]


class CreateSessionRequest(StrictModel):
    bootstrap_token: str = Field(min_length=3, max_length=300)


class CreateProjectRequest(StrictModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)


class AddProjectMemberRequest(StrictModel):
    actor_id: str = Field(min_length=1, max_length=100)
    project_role: ProjectRole


class CreateReviewInvitationRequest(StrictModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    expires_in_days: int = Field(default=7, ge=1, le=30)


class AcceptInvitationRequest(StrictModel):
    token: str = Field(min_length=20, max_length=500)


class CreateProjectReviewRequest(StrictModel):
    topic: str = Field(min_length=3, max_length=1000)
    max_results: int = Field(default=20, ge=10, le=20)
    conversation_id: str | None = None
    execution_mode: Literal["review", "autonomous"] = "review"
    response_language: Literal["Vietnamese", "English"] | None = None


class CreateResearchPlanRequest(StrictModel):
    prompt: str = Field(min_length=3, max_length=8000)
    conversation_id: str | None = None


class ApproveResearchPlanRequest(StrictModel):
    sub_queries: list[str] = Field(min_length=1, max_length=6)
    sources: list[Literal["openalex", "semantic_scholar", "arxiv"]] = Field(min_length=1, max_length=3)
    max_results: int = Field(default=20, ge=10, le=20)
    execution_mode: Literal["review", "autonomous"] = "review"


class V2ClaimReview(StrictModel):
    claim_id: str
    verdict: Literal["supported", "unsupported"]
    note: str = Field(default="", max_length=2000)


class V2ReferenceCheck(StrictModel):
    paper_id: str
    verdict: Literal["valid", "invalid"]
    note: str = Field(default="", max_length=2000)


class V2ReviewRequest(StrictModel):
    decisions: list[V2ClaimReview]
    reference_checks: list[V2ReferenceCheck]
    report_decision: Literal["approve", "request_changes"]
    report_note: str = Field(default="", max_length=2000)


class CreateConversationRequest(StrictModel):
    initial_report_version_id: str | None = None
    force_new: bool = False


class UpdateConversationRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)


class CreateMessageRequest(StrictModel):
    client_message_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=8000)
    expected_report_version_id: str | None = None
    mode: Literal["grounded", "knowledge"] = "grounded"


class SourceChatRequest(StrictModel):
    """A question grounded in a deliberately selected approved-report corpus."""

    job_ids: list[str] = Field(min_length=1, max_length=12)
    text: str = Field(min_length=1, max_length=8000)


class GenerateVisualArtifactRequest(StrictModel):
    """A user-triggered, report-derived presentation artifact."""

    artifact_type: Literal["mindmap", "slides"]
    latex: str = Field(min_length=1, max_length=100_000)


class VisualArtifactBranch(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    points: list[str] = Field(min_length=1, max_length=4)


class VisualArtifactSlide(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    subtitle: str = Field(default="", max_length=240)
    points: list[str] = Field(min_length=2, max_length=5)
    speaker_notes: str = Field(default="", max_length=2400)
    visual_prompt: str = Field(default="", max_length=1000)
    visual_alt: str = Field(default="", max_length=240)
    image_data_url: str = Field(default="", max_length=4_000_000)


class GeneratedVisualArtifact(StrictModel):
    title: str = Field(min_length=1, max_length=240)
    overview: str = Field(min_length=1, max_length=700)
    branches: list[VisualArtifactBranch] = Field(default_factory=list, max_length=6)
    slides: list[VisualArtifactSlide] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def has_one_complete_artifact(self) -> GeneratedVisualArtifact:
        if bool(self.branches) == bool(self.slides):
            raise ValueError("exactly one of branches or slides must be populated")
        return self


class ClassifyWorkspaceIntentRequest(StrictModel):
    text: str = Field(min_length=1, max_length=8000)


class MemoryCreateRequest(StrictModel):
    memory_type: MemoryType
    content: dict[str, Any]
    conversation_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    report_version_id: str | None = None
    ttl_seconds: int | None = Field(default=None, ge=60, le=31_536_000)


class SupersedeMemoryRequest(StrictModel):
    content: dict[str, Any]
    evidence_ids: list[str] = Field(default_factory=list)


class EstimatedImpact(StrictModel):
    summary: str = Field(min_length=1, max_length=2000)
    affected_paper_ids: list[str] = Field(default_factory=list)
    affected_claim_ids: list[str] = Field(default_factory=list)
    affected_gap_ids: list[str] = Field(default_factory=list)
    may_change_corpus: bool
    requires_revalidation: bool
    expected_new_papers_min: int = Field(ge=0, le=20)
    expected_new_papers_max: int = Field(ge=0, le=20)
    cost_class: Literal["low", "medium", "high"]

    @model_validator(mode="after")
    def validate_range(self) -> EstimatedImpact:
        if self.expected_new_papers_min > self.expected_new_papers_max:
            raise ValueError("expected_new_papers_min must be <= expected_new_papers_max")
        return self


class CreateActionProposalRequest(StrictModel):
    conversation_id: str | None = None
    base_report_version_id: str | None = None
    action_type: ActionType
    parameters: dict[str, Any]
    reason: str = Field(min_length=1, max_length=2000)
    source_feedback_id: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    estimated_impact: EstimatedImpact


class ApproveActionRequest(StrictModel):
    expected_status: Literal["proposed"]
    expected_base_report_version_id: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class RejectActionRequest(StrictModel):
    expected_status: Literal["proposed"]
    reason: str = Field(min_length=1, max_length=2000)


class CancelActionRequest(StrictModel):
    reason: str = Field(min_length=1, max_length=2000)


class GapCountersearchRequest(StrictModel):
    report_version_id: str
    query: str = Field(min_length=3, max_length=300)
    limit: int = Field(default=10, ge=1, le=20)


class GapReviewRequest(StrictModel):
    report_version_id: str
    verdict: Literal["approve", "narrow", "reject", "request_more_evidence"]
    revised_statement: str | None = Field(default=None, max_length=3000)
    note: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def narrow_requires_statement(self) -> GapReviewRequest:
        if self.verdict == "narrow" and not self.revised_statement:
            raise ValueError("narrow requires revised_statement")
        return self


class V2MetricsResponse(StrictModel):
    factual_answers: int
    cited_factual_answers: int
    factual_answer_citation_coverage: float
    invalid_citations: int
    unconfirmed_mutations: int
    stale_actions_applied: int
    active_fact_memories: int
    invalid_fact_memories: int
    gaps_reviewed: int
    approved_gaps_with_full_coverage: int
    mvp2_policy_passed: bool
