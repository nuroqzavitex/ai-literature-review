"""Research-question, AnalysisPlan, and review-decision contracts for S3."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AnalysisObjective(StrEnum):
    DESCRIBE = "describe"
    COMPARE = "compare"
    ASSOCIATE = "associate"
    PREDICT = "predict"


class AnalysisIntent(BaseModel):
    """Human-supplied analysis choices. Empty lists trigger clarification, never guesses."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective: AnalysisObjective
    research_question: str = Field(min_length=1, max_length=10_000)
    outcome_columns: list[str] = Field(default_factory=list)
    predictor_columns: list[str] = Field(default_factory=list)
    group_columns: list[str] = Field(default_factory=list)
    covariate_columns: list[str] = Field(default_factory=list)
    study_design: str | None = Field(default=None, max_length=2_000)
    repeated_measures: bool | None = None
    hypothesis: str | None = Field(default=None, max_length=10_000)
    preferred_metrics: list[str] = Field(default_factory=list)
    output_language: Literal["vi", "en"] = "vi"


class CreateAnalysisQuestionRequest(AnalysisIntent):
    """Optional reference to a server-stored, project-scoped pinned context."""

    context_snapshot_id: str | None = Field(default=None, min_length=1, max_length=255)


class AnalysisQuestionClarification(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["question_incomplete"] = "question_incomplete"
    question_id: str | None = None
    missing_fields: list[str] = Field(min_length=1)
    clarification_questions: list[str] = Field(default_factory=list)


class AnalysisPlanStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    SUPERSEDED = "superseded"


class AnalysisPlanContent(BaseModel):
    """Strict AI output. Server-owned lineage and column choices are never AI generated."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(min_length=1, max_length=2_000)
    method_rationale: str = Field(min_length=1, max_length=10_000)
    preprocessing_steps: list[str] = Field(default_factory=list)
    assumption_checks: list[str] = Field(default_factory=list)
    evaluation_metrics: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AnalysisPlanVersion(AnalysisPlanContent):
    """Immutable plan content with a mutable lifecycle status only."""

    model_config = ConfigDict(frozen=True)

    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    dataset_id: str
    question_id: str
    question_version: int = Field(ge=1)
    profile_version: int = Field(ge=1)
    context_snapshot_id: str | None = None
    context_hash: str | None = None
    version: int = Field(default=1, ge=1)
    status: AnalysisPlanStatus = AnalysisPlanStatus.DRAFT
    objective: AnalysisObjective
    research_question: str
    outcome_columns: list[str]
    predictor_columns: list[str]
    group_columns: list[str]
    covariate_columns: list[str]
    output_language: Literal["vi", "en"] = "vi"
    plan_hash: str
    prompt_version: Literal["analysis.plan_generation.v1"] = "analysis.plan_generation.v1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreateAnalysisPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1, max_length=255)
    profile_version: int | None = Field(default=None, ge=1)


class AnalysisPlanDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    plan_id: str
    plan_version: int = Field(ge=1)
    reviewer_id: str
    decision: AnalysisPlanStatus
    comment: str | None = Field(default=None, max_length=10_000)
    idempotency_key: str = Field(min_length=1, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewAnalysisPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: AnalysisPlanStatus
    comment: str | None = Field(default=None, max_length=10_000)
