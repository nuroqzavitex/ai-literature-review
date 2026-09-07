"""Immutable hypothesis and experiment draft contracts."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class DraftStatus(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class EvidenceStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    INSUFFICIENT = "insufficient_evidence"


class HypothesisDraftContent(BaseModel):
    """Strict content expected from the project AI gateway, without identity fields."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=10_000)
    rationale: str = Field(min_length=1, max_length=20_000)
    supporting_evidence_refs: list[str] = Field(default_factory=list)
    counterevidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    falsification_criteria: list[str] = Field(default_factory=list)
    required_data: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class HypothesisDraft(HypothesisDraftContent):
    model_config = ConfigDict(frozen=True)

    hypothesis_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    version: int = Field(default=1, ge=1)
    status: DraftStatus = DraftStatus.DRAFT
    evidence_status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExperimentDraftContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=10_000)
    independent_variables: list[str] = Field(default_factory=list)
    dependent_variables: list[str] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)
    method_candidates: list[str] = Field(default_factory=list)
    evaluation_metrics: list[str] = Field(default_factory=list)
    assumption_checks: list[str] = Field(default_factory=list)
    stopping_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ExperimentDraft(ExperimentDraftContent):
    model_config = ConfigDict(frozen=True)

    experiment_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    hypothesis_id: str
    version: int = Field(default=1, ge=1)
    status: DraftStatus = DraftStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GenerateHypothesisRequest(BaseModel):
    """Optional human clarification; identity, evidence and context stay server-side."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str | None = Field(default=None, max_length=10_000)
    output_language: Literal["vi", "en"] = "vi"


class GenerateExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(min_length=1)
    output_language: Literal["vi", "en"] = "vi"


class ReviewHypothesisDraftRequest(BaseModel):
    """A reviewer can only accept or reject an immutable draft version."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["reviewed", "rejected"]
