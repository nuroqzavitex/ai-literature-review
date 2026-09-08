"""Stable, least-privilege response contracts consumed by the product frontend."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sandbox_service.domain.execution import AnalysisCodeStatus, AnalysisCodeVersion, SandboxRun, SandboxRunStatus


class SandboxModeCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    hypothesis: bool
    graph_overlay: bool
    data_analysis: bool


class SandboxCapabilitiesResponse(BaseModel):
    """Public capability discovery; contains no deployment secret or internal URL."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["sandbox_capabilities.v1"] = "sandbox_capabilities.v1"
    enabled: bool
    modes: SandboxModeCapabilities
    ai_enabled: bool
    graph_context_enabled: bool
    result_interpretation_enabled: bool
    supported_dataset_formats: tuple[Literal["csv", "xlsx", "parquet"], ...] = (
        "csv",
        "xlsx",
        "parquet",
    )
    max_dataset_bytes: int = 50 * 1024 * 1024
    max_overlay_hops: Literal[2] = 2
    run_polling_supported: Literal[True] = True


class PublicSandboxRun(BaseModel):
    """Browser-safe run view; manifest signatures, leases and storage internals stay private."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    operation_id: str
    project_id: str
    dataset_id: str
    plan_id: str
    plan_version: int
    code_version_id: str
    status: SandboxRunStatus
    error_code: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, run: SandboxRun) -> "PublicSandboxRun":
        return cls.model_validate(run.model_dump(exclude={"manifest", "idempotency_key", "plan_decision_id", "lease_owner", "lease_expires_at"}))


class PublicAnalysisCode(BaseModel):
    """Exact immutable Python source attached to a project-scoped run."""

    model_config = ConfigDict(frozen=True)

    code_version_id: str
    code_id: str
    run_id: str
    plan_id: str
    plan_version: int
    version: int
    source_code: str
    code_hash: str
    prompt_version: Literal["analysis.code_generation.v1", "analysis.code_revision.v1"]
    status: AnalysisCodeStatus
    revision_count: int
    created_at: datetime

    @classmethod
    def from_domain(cls, *, run: SandboxRun, code: AnalysisCodeVersion) -> "PublicAnalysisCode":
        return cls(run_id=run.run_id, **code.model_dump(exclude={"project_id"}))


class AnalysisArtifactSummary(BaseModel):
    """Artifact metadata with a scoped download URL instead of an object-store key."""

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    run_id: str
    artifact_type: Literal["result", "table", "chart", "diagnostic"]
    filename: str
    content_hash: str
    size_bytes: int = Field(ge=0)
    download_url: str


class AdoptionHandOffResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal_id: str
    core_draft_id: str
    status: Literal["draft_created"] = "draft_created"


class SandboxErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    error_code: str
    message: str
    retryable: bool = False
    details: dict[str, object] = Field(default_factory=dict)
    correlation_id: str | None = None


class SandboxErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    detail: SandboxErrorDetail
