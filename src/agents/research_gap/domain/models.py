"""Domain contracts for corpus-scoped research-gap detection."""

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

GapType = Literal["topical", "method", "contradiction", "evaluation"]
GapOrigin = Literal["explicit", "limitation", "inferred"]
Verdict = Literal["supported", "partial", "unsupported", "uncertain"]


class GapQuery(BaseModel):
    core_topic: str = Field(min_length=3, max_length=500)
    facets: list[str] = Field(default_factory=list, max_length=4)
    required_terms: list[str] = Field(default_factory=list, max_length=3)
    year_range: tuple[int, int] | None = None
    recency_bias: bool = False
    seminal_bias: bool = False
    is_research_topic: bool = True
    relevance_gate: bool = True


class ExtractedPaper(BaseModel):
    paper_id: str
    topics: list[str] = Field(default_factory=list, max_length=8)
    methodology: str = ""
    dataset: str = ""
    population: str = ""
    metrics: list[str] = Field(default_factory=list, max_length=8)
    key_claims: list[str] = Field(default_factory=list, max_length=5)
    limitation_statements: list[str] = Field(default_factory=list, max_length=5)


class ExtractionResult(BaseModel):
    papers: list[ExtractedPaper] = Field(default_factory=list)


class CandidateEvidence(BaseModel):
    paper_id: str
    evidence_quote: str = Field(min_length=1, max_length=1000)


class GapCandidate(BaseModel):
    aspect: str = Field(min_length=3, max_length=500)
    statement: str = Field(min_length=8, max_length=1000)
    evidence: list[CandidateEvidence] = Field(min_length=1, max_length=5)
    counter_search_query: str = Field(min_length=3, max_length=300)
    reviewer_rationale: str = Field(min_length=3, max_length=1000)
    suggested_method: str = Field(min_length=3, max_length=1000)
    falsification_condition: str = Field(min_length=3, max_length=1000)


class DetectorResult(BaseModel):
    candidates: list[GapCandidate] = Field(default_factory=list, max_length=3)


class OriginAssessment(BaseModel):
    index: int = Field(ge=0)
    origin: GapOrigin
    rationale: str = Field(min_length=3, max_length=500)


class OriginResult(BaseModel):
    origins: list[OriginAssessment] = Field(default_factory=list)


class AtomicAssessment(BaseModel):
    statement: str = Field(min_length=3, max_length=500)
    verdict: Verdict


class VerificationAssessment(BaseModel):
    index: int = Field(ge=0)
    verdict: Verdict
    rationale: str = Field(min_length=3, max_length=500)
    subclaims: list[AtomicAssessment] = Field(min_length=1, max_length=5)


class VerificationResult(BaseModel):
    assessments: list[VerificationAssessment] = Field(default_factory=list)


class CounterAssessment(BaseModel):
    index: int = Field(ge=0)
    directly_addresses: list[CandidateEvidence] = Field(default_factory=list, max_length=5)


class CounterAssessmentResult(BaseModel):
    assessments: list[CounterAssessment] = Field(default_factory=list)


class ResearchGapState(TypedDict, total=False):
    topic: str
    language: str
    papers: list[dict[str, Any]]
    extracted: dict[str, dict[str, Any]]
    topical: list[dict[str, Any]]
    method: list[dict[str, Any]]
    contradiction: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    verified: list[dict[str, Any]]
    countersearch: dict[str, list[dict[str, Any]]]
    gaps: list[dict[str, Any]]
    narrative: str
