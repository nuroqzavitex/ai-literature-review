"""Durable run, manifest, code-version, and artifact contracts for S5."""

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SandboxRunStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED_UNVALIDATED = "completed_unvalidated"
    VALIDATION_FAILED = "validation_failed"
    RESULT_REVIEW_WAITING = "result_review_waiting"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    POLICY_REJECTED = "policy_rejected"
    CANCELLED = "cancelled"


class AnalysisCodeStatus(StrEnum):
    DRAFT = "draft"
    POLICY_REJECTED = "policy_rejected"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class AnalysisCodeVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    code_version_id: str = Field(default_factory=lambda: str(uuid4()))
    code_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    plan_id: str
    plan_version: int = Field(ge=1)
    version: int = Field(default=1, ge=1)
    source_code: str = Field(min_length=1)
    code_hash: str
    prompt_version: Literal["analysis.code_generation.v1", "analysis.code_revision.v1"]
    status: AnalysisCodeStatus = AnalysisCodeStatus.DRAFT
    revision_count: int = Field(default=0, ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GeneratedCode(BaseModel):
    """Only source text is returned by ProjectAIClient; lineage is server-owned."""

    model_config = ConfigDict(extra="forbid")

    source_code: str = Field(min_length=1, max_length=50_000)


class SandboxExecutionManifest(BaseModel):
    """Signed immutable worker input. No secret or raw dataset bytes are present."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["sandbox_execution.v1"] = "sandbox_execution.v1"
    operation_id: str
    run_id: str
    project_id: str
    dataset_id: str
    dataset_content_hash: str
    staged_input_path: str | None = None
    plan_id: str
    plan_version: int = Field(ge=1)
    plan_hash: str
    plan_decision_id: str
    action_proposal_id: str | None = None
    code_version_id: str
    code_hash: str
    image_digest: str
    package_manifest_hash: str
    random_seed: int = Field(ge=0)
    resource_limits: dict[str, Any]
    output_contract_version: str = "analysis_result.v1"
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=15))
    nonce: str
    signature: str = ""


class SandboxRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    operation_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    dataset_id: str
    plan_id: str
    plan_version: int
    plan_decision_id: str
    code_version_id: str
    idempotency_key: str
    status: SandboxRunStatus = SandboxRunStatus.QUEUED
    manifest: SandboxExecutionManifest
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    error_code: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SandboxRunStatusHistory(BaseModel):
    model_config = ConfigDict(frozen=True)

    history_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    project_id: str
    from_status: SandboxRunStatus | None = None
    to_status: SandboxRunStatus
    changed_by: str
    reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnalysisArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    run_id: str
    artifact_type: Literal["result", "table", "chart", "diagnostic"]
    filename: str
    content_hash: str
    size_bytes: int = Field(ge=0)
    storage_key: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreateSandboxRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    random_seed: int = Field(default=42, ge=0)


class QueuedRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation_id: str
    resource_id: str
    status: Literal["queued"] = "queued"
    status_url: str
