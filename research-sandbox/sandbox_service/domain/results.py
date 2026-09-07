"""Validated result, review, citation, and sealed reproducibility contracts."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ResultValidationStatus(StrEnum):
    VALIDATED = "validated"
    FAILED = "failed"


class AnalysisMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    name: str = Field(min_length=1, max_length=255)
    value: int | float | str | bool | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PredictionDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_column: str = Field(min_length=1)
    feature_columns: list[str] = Field(default_factory=list)
    train_row_count: int = Field(ge=0)
    test_row_count: int = Field(ge=0)
    train_row_ids: list[str] | None = None
    test_row_ids: list[str] | None = None


class AnalysisResult(BaseModel):
    """Strict, data-free structured output accepted from a sandbox runtime."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["analysis_result.v1"]
    objective: Literal["describe", "compare", "associate", "predict"]
    method: str = Field(min_length=1, max_length=2_000)
    input_row_count: int = Field(ge=0)
    analyzed_row_count: int = Field(ge=0)
    preprocessing_applied: list[str] = Field(default_factory=list)
    assumption_checks: list[dict[str, Any]] = Field(min_length=1)
    metrics: list[AnalysisMetric] = Field(default_factory=list)
    statistical_results: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    narrative: list[str] = Field(default_factory=list)
    prediction_diagnostics: PredictionDiagnostics | None = None


class AnalysisResultValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    validation_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    run_id: str
    result_hash: str | None = None
    status: ResultValidationStatus
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validator_version: str = "result_validator.v1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InterpretationNumericClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    statement: str = Field(min_length=1, max_length=2_000)
    value: int | float = Field()
    locator: str = Field(pattern=r"^/(metrics|statistical_results)/\d+(/[^/]+)*$")


class ResultInterpretation(BaseModel):
    """AI output where all numeric content is structured and citable."""

    model_config = ConfigDict(extra="forbid")

    narrative: list[str] = Field(default_factory=list)
    numeric_claims: list[InterpretationNumericClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AnalysisResultInterpretationRecord(BaseModel):
    """Durable frontend view of one validation-gated AI interpretation."""

    model_config = ConfigDict(frozen=True)

    interpretation_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    run_id: str
    validation_id: str
    prompt_version: Literal["analysis.result_interpretation.v1"] = "analysis.result_interpretation.v1"
    narrative: list[str] = Field(default_factory=list)
    numeric_claims: list[InterpretationNumericClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnalysisCitation(BaseModel):
    model_config = ConfigDict(frozen=True)

    citation_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    dataset_id: str
    dataset_hash: str
    profile_version: int | None = None
    plan_id: str
    plan_version: int
    run_id: str
    artifact_id: str
    artifact_type: str
    locator: str
    value_hash: str
    validation_status: Literal["validated", "reviewed"] = "validated"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResultReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class AnalysisResultReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    run_id: str
    validation_id: str
    reviewer_id: str
    decision: ResultReviewDecision
    comment: str | None = Field(default=None, max_length=10_000)
    idempotency_key: str = Field(min_length=1, max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewAnalysisResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: ResultReviewDecision
    comment: str | None = Field(default=None, max_length=10_000)


class ResultReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_status: Literal["approved", "rejected"]
    review: AnalysisResultReview


class AnalysisReproducibilityBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    bundle_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    run_id: str
    dataset_hash: str
    profile_hash: str
    research_context_hash: str | None = None
    plan_hash: str
    plan_decision_id: str
    action_proposal_id: str | None = None
    code_hash: str
    prompt_version: str
    model_route_audit_id: str
    image_digest: str
    package_manifest_hash: str
    random_seed: int
    result_hash: str
    artifact_hashes: list[str]
    bundle_hash: str
    sealed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
