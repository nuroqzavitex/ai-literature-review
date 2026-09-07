from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["researcher", "reviewer"]
JobStatus = Literal[
    "queued",
    "running",
    "resuming",
    "hitl_waiting",
    "approved",
    "changes_requested",
    "cancelled",
    "error",
]
ClaimType = Literal[
    "method",
    "dataset",
    "contribution",
    "limitation",
    "theme",
    "potential_gap",
]
DecisionAction = Literal[
    "continue",
    "refine_query",
    "skip_potential_gaps",
    "reject_claim",
    "revise_claims",
    "wait_for_human",
    "finish",
    "fail",
]


class LitReviewRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=1000)
    max_results: int = Field(default=20, ge=10, le=20)
    user_id: str = Field(..., min_length=1, max_length=100)
    role: Role = "researcher"
    execution_mode: Literal["review", "autonomous"] = "review"
    response_language: Literal["Vietnamese", "English"] | None = None

    @field_validator("topic")
    @classmethod
    def normalize_topic(cls, value: str) -> str:
        return " ".join(value.split())


class JobStartResponse(BaseModel):
    job_id: str
    thread_id: str
    status: Literal["queued"]


class DecisionSummaryResponse(BaseModel):
    action: DecisionAction
    reason: str


class NodeTraceResponse(BaseModel):
    trace_id: str
    node: str
    summary: str
    created_at: str
    papers_found: int = 0


class PaperIngestionResponse(BaseModel):
    content_availability: Literal["full_text", "abstract_only"]
    ingestion_status: Literal["succeeded", "unavailable", "failed"]
    full_text_source: Literal["pdf", "pmc_xml", "html"] | None = None
    full_text_url: str | None = None
    full_text_chunks: int = Field(default=0, ge=0)
    ingestion_warning: str | None = None


class ProgressPaperResponse(BaseModel):
    paper_id: str
    source: str = "unknown"
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    url: str = ""
    cited_by_count: int = 0
    relevance_score: float | None = None
    ingestion: PaperIngestionResponse | None = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    current_node: str
    papers_found: int
    valid_claims: int = 0
    search_attempt: int = 0
    grounding_revision_attempt: int = 0
    review_revision_attempt: int = 0
    search_query: str | None = None
    query_history: list[str] = Field(default_factory=list)
    sub_queries: list[str] = Field(default_factory=list)
    selected_paper_ids: list[str] = Field(default_factory=list)
    embedding_backend: Literal["primary", "fallback"] | None = None
    embedding_collection: str | None = None
    hitl_stage: Literal["subqueries", "papers", "review"] | None = None
    execution_mode: Literal["review", "autonomous"] = "review"
    last_decision: DecisionSummaryResponse | None = None
    warnings: list[str] = Field(default_factory=list)
    node_trace: list[NodeTraceResponse] = Field(default_factory=list)
    papers: list[ProgressPaperResponse] = Field(default_factory=list)
    error: str | None = None


class WorkflowResumeRequest(BaseModel):
    stage: Literal["subqueries", "papers"]
    sub_queries: list[str] = Field(default_factory=list, max_length=12)
    mode: Literal["manual", "ranked"] = "ranked"
    selected_paper_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("sub_queries")
    @classmethod
    def validate_sub_query_lengths(cls, value: list[str]) -> list[str]:
        queries = [" ".join(query.split()) for query in value if query.strip()]
        if any(not 8 <= len(query.split()) <= 14 for query in queries):
            raise ValueError("Mỗi sub-query phải có từ 8 đến 14 từ")
        return queries


class PaperResponse(BaseModel):
    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    doi: str | None
    url: str
    abstract: str
    cited_by_count: int
    is_open_access: bool
    pdf_url: str | None = None
    relevance_score: float | None = None
    rank: int | None = None
    ingestion: PaperIngestionResponse | None = None


class SelectedPapersRequest(BaseModel):
    papers: list[PaperResponse] = Field(default_factory=list)
    replace_existing: bool = True


class SelectedPapersIndexResponse(BaseModel):
    job_id: str
    indexed_papers: int
    replace_existing: bool
    collection: str


class SelectedPapersQueryRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    limit: int = Field(default=10, ge=1, le=50)


class SelectedPapersQueryResponse(BaseModel):
    job_id: str
    query: str
    limit: int
    results: list[PaperResponse]


class EvidenceQuoteResponse(BaseModel):
    paper_id: str
    quote: str
    section: str
    section_type: str | None = None
    source_level: Literal["full_text", "abstract", "snippet"] = "abstract"
    document_id: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    content_hash: str | None = None
    retrieval_score: float | None = None
    context_before: str | None = None
    context_after: str | None = None


class ClaimResponse(BaseModel):
    claim_id: str
    claim_type: ClaimType
    text: str
    supporting_paper_ids: list[str]
    evidence: list[EvidenceQuoteResponse]
    validation_status: Literal["valid", "rejected"]
    validation_errors: list[str]
    evidence_confidence: Literal["high", "low"] = "low"
    requires_human_review: bool = True
    evidence_verdict: Literal["supported", "partial", "unsupported", "uncertain"] = "uncertain"


class EvidenceRowResponse(BaseModel):
    paper_id: str
    citation_label: str
    title: str
    year: int | None
    url: str
    method_claim_id: str | None
    dataset_claim_id: str | None
    contribution_claim_id: str | None
    limitation_claim_id: str | None


class LiteratureReviewSectionResponse(BaseModel):
    title: str
    paragraphs: list[str]
    supporting_paper_ids: list[str]


class LiteratureReviewResponse(BaseModel):
    title: str
    abstract: str
    introduction: str
    sections: list[LiteratureReviewSectionResponse]
    conclusion: str
    limitations: str


class ThemeResponse(BaseModel):
    theme_id: str
    title: str
    summary_claim_id: str
    supporting_paper_ids: list[str]


class GapCoverageResponse(BaseModel):
    paper_id: str
    mentioned: bool
    evidence_quote: str | None


class PotentialGapResponse(BaseModel):
    gap_id: str
    claim_id: str
    aspect: str
    papers_checked: int
    coverage: list[GapCoverageResponse]
    scope_statement: str
    gap_type: Literal["topical", "method", "contradiction", "evaluation"] | None = None
    confidence: Literal["low", "medium", "high"] | None = None
    counter_search_query: str | None = None
    reviewer_rationale: str | None = None
    verification_status: Literal["grounded", "needs_counter_search", "reviewed"] | None = None
    evidence_score: int | None = None
    novelty_score: int | None = None
    feasibility_score: int | None = None
    quality_score: int | None = None
    suggested_method: str | None = None
    falsification_condition: str | None = None
    source_type: Literal["author_stated", "corpus_inferred"] | None = None
    origin: Literal["explicit", "limitation", "inferred"] | None = None
    verification_verdict: Literal["supported", "partial", "unsupported", "uncertain"] | None = None
    counterevidence_paper_ids: list[str] = Field(default_factory=list)


class ReferenceResponse(BaseModel):
    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    doi: str | None
    url: str
    source: Literal["openalex", "semantic_scholar", "arxiv"]
    metadata_valid: bool


class AgentDecisionResponse(BaseModel):
    decision_id: str
    node: str
    action: DecisionAction
    reason: str
    created_at: str


class ReviewSummaryResponse(BaseModel):
    total_claims: int
    reviewed_claims: int
    supported_claims: int
    unsupported_claims: int


class RevisionRecordResponse(BaseModel):
    revision_id: str
    claim_id: str
    source: Literal["grounding", "reviewer"]
    action: Literal["revise", "narrow", "discard"]
    reason: str
    review_round: int
    revised_text: str
    previous_text: str


class ReviewDecisionResponse(BaseModel):
    claim_id: str
    verdict: Literal["supported", "unsupported"]
    note: str


class ReferenceCheckResponse(BaseModel):
    paper_id: str
    verdict: Literal["valid", "invalid"]
    note: str


class ReviewAuditResponse(BaseModel):
    reviewer_id: str
    report_decision: Literal["approve", "request_changes"]
    report_note: str
    reviewed_at: str
    decisions: list[ReviewDecisionResponse]
    reference_checks: list[ReferenceCheckResponse]


class LitReviewResultResponse(BaseModel):
    job_id: str
    status: JobStatus
    topic: str
    original_topic: str
    intent: Literal["litreview", "research_gap", "out_of_scope", "unsafe"] = "litreview"
    assistant_response: str = ""
    response_language: str | None = None
    search_query: str
    query_history: list[str]
    papers_count: int
    papers: list[PaperResponse]
    claims: list[ClaimResponse]
    evidence_rows: list[EvidenceRowResponse]
    themes: list[ThemeResponse]
    potential_gaps: list[PotentialGapResponse]
    references: list[ReferenceResponse]
    scope_disclaimer: str
    narrative: str = ""
    literature_review: LiteratureReviewResponse | None = None
    decision_trace: list[AgentDecisionResponse]
    revision_log: list[RevisionRecordResponse] = Field(default_factory=list)
    source_warnings: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    search_attempt: int = 0
    grounding_revision_attempt: int = 0
    review_revision_attempt: int = 0
    review_summary: ReviewSummaryResponse
    review: ReviewAuditResponse | None = None


class ProviderRouteResponse(BaseModel):
    provider: str
    model: str


class AgentStatusResponse(BaseModel):
    status: Literal["configured", "misconfigured"]
    agent: str
    providers: list[ProviderRouteResponse]
    failover_enabled: bool
    runtime_verified: Literal[False] = False
    detail: str


class ReviewDecisionRequest(BaseModel):
    claim_id: str
    verdict: Literal["supported", "unsupported"]
    note: str = Field(default="", max_length=2000)


class ReferenceCheckRequest(BaseModel):
    paper_id: str
    verdict: Literal["valid", "invalid"]
    note: str = Field(default="", max_length=2000)


class ReviewRequest(BaseModel):
    reviewer_id: str = Field(..., min_length=1, max_length=100)
    role: Role
    decisions: list[ReviewDecisionRequest]
    reference_checks: list[ReferenceCheckRequest]
    report_decision: Literal["approve", "request_changes"]
    report_note: str = Field(default="", max_length=2000)


class ReviewResponse(BaseModel):
    job_id: str
    status: Literal["approved", "changes_requested", "resuming"]
    reviewed_claims: int
    supported_claims: int
    unsupported_claims: int
    claim_support_accuracy: float | None
    checked_references: int
    valid_references: int
    invalid_references: int
    reference_validity: float | None


class EvaluationRequest(BaseModel):
    evaluator_id: str
    manual_minutes: float = Field(..., gt=0.0)
    mvp_minutes: float = Field(..., gt=0.0)
    usefulness_score: float = Field(..., ge=1.0, le=5.0)
    notes: str = ""


class EvaluationResponse(EvaluationRequest):
    job_id: str
    evaluated_at: str


class MVPMetricsResponse(BaseModel):
    reports_evaluated: int
    claims_reviewed: int
    supported_claims: int
    claim_support_accuracy: float
    claim_review_coverage: float
    references_checked: int
    valid_references: int
    reference_validity: float
    reference_review_coverage: float
    median_time_reduction: float
    mvp_passed: bool


class JobListItem(BaseModel):
    job_id: str
    topic: str
    user_id: str
    status: JobStatus
    papers_found: int
    created_at: str
