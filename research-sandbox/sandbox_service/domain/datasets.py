"""Dataset, profile, and structured analysis-question contracts."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class DatasetClassification(StrEnum):
    NON_SENSITIVE = "non_sensitive"
    UNKNOWN = "unknown"
    RESTRICTED = "restricted"


class DatasetStatus(StrEnum):
    STAGED = "staged"
    VALIDATED = "validated"
    REJECTED = "rejected"
    DELETED = "deleted"


class DatasetUploadResult(BaseModel):
    """Metadata only. Raw bytes never leave storage through this schema."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    filename: str
    media_type: str
    size_bytes: int = Field(ge=0)
    content_hash: str
    classification: DatasetClassification
    status: DatasetStatus
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DatasetRecord(DatasetUploadResult):
    """Sandbox persistence metadata; this is not returned by public upload/list APIs."""

    model_config = ConfigDict(frozen=True)

    owner_id: str
    storage_key: str
    retention_until: datetime | None = None
    deleted_at: datetime | None = None


class DatasetColumnProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    dtype: str
    missing_count: int = Field(ge=0)
    missing_ratio: float = Field(ge=0, le=1)
    unique_count: int = Field(ge=0)
    distribution: dict[str, Any]


class DatasetProfile(BaseModel):
    """Immutable deterministic profile tied to one content hash and profiler version."""

    model_config = ConfigDict(frozen=True)

    profile_id: str = Field(default_factory=lambda: str(uuid4()))
    dataset_id: str
    project_id: str
    version: int = Field(ge=1)
    profiler_version: str = "dataset_profiler.v1"
    content_hash: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    columns: list[DatasetColumnProfile]
    profile_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnalysisQuestionStatus(StrEnum):
    DRAFT = "draft"
    QUESTION_INCOMPLETE = "question_incomplete"


class AnalysisQuestion(BaseModel):
    """S2 persistence contract for a human-confirmed analysis question."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    dataset_id: str
    profile_version: int | None = Field(default=None, ge=1)
    context_snapshot_id: str | None = None
    context_hash: str | None = None
    version: int = Field(default=1, ge=1)
    objective: Literal["describe", "compare", "associate", "predict"]
    research_question: str = Field(min_length=1, max_length=10_000)
    outcome_columns: list[str] = Field(default_factory=list)
    predictor_columns: list[str] = Field(default_factory=list)
    group_columns: list[str] = Field(default_factory=list)
    covariate_columns: list[str] = Field(default_factory=list)
    study_design: str | None = None
    repeated_measures: bool | None = None
    hypothesis: str | None = None
    preferred_metrics: list[str] = Field(default_factory=list)
    output_language: Literal["vi", "en"] = "vi"
    status: AnalysisQuestionStatus = AnalysisQuestionStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
