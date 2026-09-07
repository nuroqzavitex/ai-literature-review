"""Typed domain state shared by the LitReview workflow and its adapters."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

Role = Literal["researcher", "reviewer"]

JobStatus = Literal[
    "queued",
    "running",
    "resuming",
    "hitl_waiting",
    "approved",
    "changes_requested",
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

EvidenceVerdict = Literal["supported", "partial", "unsupported", "uncertain"]


class AgentDecision(TypedDict):
    decision_id: str
    node: str
    action: Literal[
        "continue",
        "refine_query",
        "skip_potential_gaps",
        "reject_claim",
        "revise_claims",
        "wait_for_human",
        "finish",
        "fail",
    ]
    reason: str
    created_at: str


class PaperIngestion(TypedDict):
    """Job-specific full-text ingestion outcome for one paper."""

    content_availability: Literal["full_text", "abstract_only"]
    ingestion_status: Literal["succeeded", "unavailable", "failed"]
    full_text_source: Literal["pdf", "pmc_xml", "html"] | None
    full_text_url: str | None
    full_text_chunks: int
    ingestion_warning: str | None


class Paper(TypedDict):
    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    doi: str | None
    url: str
    abstract: str
    cited_by_count: int
    is_open_access: bool
    pdf_url: NotRequired[str | None]
    source: NotRequired[Literal["openalex", "semantic_scholar", "arxiv"]]
    relevance_score: NotRequired[float]
    rank: NotRequired[int]
    relevance_label: NotRequired[Literal["direct", "supporting", "background", "irrelevant"]]
    relevance_reason: NotRequired[str]
    ingestion: NotRequired[PaperIngestion]


class EvidenceQuote(TypedDict):
    paper_id: str
    quote: str
    # "full_text" evidence is retrieved from an indexed paper passage.  The
    # remaining fields make a citation independently inspectable in the review
    # UI and in exported reports.
    section: str
    section_type: NotRequired[str]
    source_level: NotRequired[Literal["full_text", "abstract", "snippet"]]
    document_id: NotRequired[str]
    start_char: NotRequired[int]
    end_char: NotRequired[int]
    content_hash: NotRequired[str]
    retrieval_score: NotRequired[float]
    context_before: NotRequired[str]
    context_after: NotRequired[str]


class ClaimCandidate(TypedDict):
    claim_id: NotRequired[str]
    claim_type: ClaimType
    text: str
    supporting_paper_ids: list[str]
    evidence: list[EvidenceQuote]


class Claim(ClaimCandidate):
    claim_id: str
    validation_status: Literal["valid", "rejected"]
    validation_errors: list[str]
    evidence_confidence: NotRequired[Literal["high", "low"]]
    requires_human_review: NotRequired[bool]
    evidence_verdict: NotRequired[EvidenceVerdict]


class EvidenceRow(TypedDict):
    paper_id: str
    citation_label: str
    title: str
    year: int | None
    url: str
    method_claim_id: str | None
    dataset_claim_id: str | None
    contribution_claim_id: str | None
    limitation_claim_id: str | None


class LiteratureReviewSection(TypedDict):
    title: str
    paragraphs: list[str]
    supporting_paper_ids: list[str]


class LiteratureReview(TypedDict):
    title: str
    abstract: str
    introduction: str
    sections: list[LiteratureReviewSection]
    conclusion: str
    limitations: str


class Theme(TypedDict):
    theme_id: str
    title: str
    summary_claim_id: str
    supporting_paper_ids: list[str]


class GapCoverage(TypedDict):
    paper_id: str
    mentioned: bool
    evidence_quote: str | None


class PotentialGap(TypedDict):
    gap_id: str
    claim_id: str
    aspect: str
    papers_checked: int
    coverage: list[GapCoverage]
    scope_statement: str
    gap_type: NotRequired[Literal["topical", "method", "contradiction", "evaluation"]]
    confidence: NotRequired[Literal["low", "medium", "high"]]
    counter_search_query: NotRequired[str]
    reviewer_rationale: NotRequired[str]
    verification_status: NotRequired[Literal["grounded", "needs_counter_search", "reviewed"]]
    evidence_score: NotRequired[int]
    novelty_score: NotRequired[int]
    feasibility_score: NotRequired[int]
    quality_score: NotRequired[int]
    suggested_method: NotRequired[str]
    falsification_condition: NotRequired[str]
    source_type: NotRequired[Literal["author_stated", "corpus_inferred"]]


class Reference(TypedDict):
    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    doi: str | None
    url: str
    source: Literal["openalex", "semantic_scholar", "arxiv"]
    metadata_valid: bool


class ReferenceCheck(TypedDict):
    paper_id: str
    verdict: Literal["valid", "invalid"]
    note: str


class ReviewDecision(TypedDict):
    claim_id: str
    verdict: Literal["supported", "unsupported"]
    note: str


class EvaluationRecord(TypedDict):
    job_id: str
    evaluator_id: str
    manual_minutes: float
    mvp_minutes: float
    usefulness_score: int
    notes: str


RevisionSource = Literal["grounding", "reviewer"]


class RevisionRecord(TypedDict):
    """Lineage entry for a single claim revision.

    claim_id stays stable across revisions; revision_id is the versioned key.
    This keeps theme/gap/evidence/review_decision references intact.
    """

    revision_id: str  # e.g. "C12-R1"
    claim_id: str  # stable — same as the original claim
    source: RevisionSource
    action: Literal["revise", "narrow", "discard"]
    reason: str
    review_round: int  # 1-based: grounding=1, reviewer=1, etc.
    revised_text: str  # new text (empty for discard)
    previous_text: str  # text before this revision


class AgentState(TypedDict, total=False):
    execution_mode: Literal["review", "autonomous"]
    # Stable correlation id for all LLM/provider events belonging to one run.
    run_id: str
    # The backend chosen when semantic ranking first runs. Every downstream
    # indexing/query call for this job must use the same vector space.
    embedding_backend: Literal["primary", "fallback"]
    embedding_collection: str
    response_language: NotRequired[Literal["Vietnamese", "English"] | None]
    synthesis_completed: bool
    job_id: str
    thread_id: str
    # Stable session boundary.  A graph checkpoint is keyed by job/thread, but
    # the conversation id is also carried through the graph so persistence and
    # resume can never fall back to a process-global conversation.
    session_id: str
    conversation_id: str | None
    original_topic: str
    intent: Literal["litreview", "unsafe", "out_of_scope"]
    intent_reason: str
    assistant_response: str
    search_query: str
    normalized_question: str
    max_results: int
    user_id: str
    conversation_history: list[dict[str, str]]

    search_attempt: int
    max_search_attempts: int
    grounding_revision_attempt: int
    review_revision_attempt: int
    max_claim_revision_attempts: int
    # Explicit source of the current revision — set by validate_grounding_node
    # (grounding) or by human_review_node (reviewer). Never inferred from
    # unsupported_ids inside revise_claims_node.
    revision_source: RevisionSource | None
    query_history: list[str]
    # User-reviewable search plan.  Each approved query is searched independently.
    sub_queries: list[str]
    # Query-planner intent guardrails. Required terms describe the intended
    # discipline/concepts; excluded terms prevent common false-positive domains.
    required_terms: list[str]
    excluded_terms: list[str]
    # Optional hard publication-date constraint extracted from the user's
    # request. A missing value means no year filtering is applied.
    publication_year_range: tuple[int | None, int | None] | None
    selected_paper_ids: list[str]
    hitl_stage: Literal["subqueries", "papers", "review"] | None
    decisions: list[AgentDecision]

    papers: list[Paper]
    source_warnings: list[str]

    claim_candidates: list[ClaimCandidate]
    claims: list[Claim]
    evidence_rows: list[EvidenceRow]
    themes: list[Theme]
    potential_gaps: list[PotentialGap]
    references: list[Reference]
    scope_disclaimer: str
    gap_analysis_completed: bool
    literature_review: LiteratureReview | None

    rejected_claims: list[Claim]
    validation_warnings: list[str]
    revision_log: list[RevisionRecord]

    status: JobStatus
    current_node: str
    hitl_payload: dict | None
    hitl_decision: Literal["approve", "request_changes"] | None
    review_decisions: list[ReviewDecision]
    reference_checks: list[ReferenceCheck]
    review_feedback: str
    error: str | None
