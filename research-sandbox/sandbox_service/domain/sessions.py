"""Immutable S0 request, trusted-context, and session schemas."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SandboxMode(StrEnum):
    HYPOTHESIS = "hypothesis"
    GRAPH_OVERLAY = "graph_overlay"
    DATA_ANALYSIS = "data_analysis"


class SandboxEntrypoint(StrEnum):
    MANUAL = "manual"
    GRAPHRAG_ANSWER = "graphrag_answer"
    VALIDATED_CANDIDATE = "validated_candidate"
    EXPERIMENT_PROPOSAL = "experiment_proposal"


class SandboxSessionStatus(StrEnum):
    DRAFT = "draft"
    CONTEXT_READY = "context_ready"
    ACTIVE = "active"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    DISCARDED = "discarded"
    STALE = "stale"
    FAILED = "failed"


class CreateSandboxSessionRequest(BaseModel):
    """Client input. It deliberately cannot carry a raw context or actor identity."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: SandboxMode
    entrypoint: SandboxEntrypoint
    source_resource_id: str | None = Field(default=None, min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    initial_question: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def validate_source_contract(self) -> "CreateSandboxSessionRequest":
        if self.entrypoint is SandboxEntrypoint.MANUAL and self.source_resource_id:
            raise ValueError("manual entrypoint cannot specify source_resource_id")
        if self.entrypoint is not SandboxEntrypoint.MANUAL and not self.source_resource_id:
            raise ValueError("a non-manual entrypoint requires source_resource_id")
        return self


class ResearchContextSnapshot(BaseModel):
    """A trusted, version-pinned context supplied only by a gateway adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["research_context.v1"] = "research_context.v1"
    context_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str = Field(min_length=1, max_length=255)
    source_type: SandboxEntrypoint
    source_resource_id: str | None = None
    graph_version_id: str | None = None
    shared_graph_version_id: str | None = None
    discovery_run_id: str | None = None
    candidate_id: str | None = None
    experiment_proposal_id: str | None = None
    research_question_suggestion: str | None = None
    objective_suggestion: str | None = None
    method_suggestions: list[str] = Field(default_factory=list)
    dataset_requirements: list[str] = Field(default_factory=list)
    evaluation_metric_suggestions: list[str] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_status: str = Field(min_length=1)
    content_hash: str = Field(min_length=1, max_length=128)
    signing_key_id: str | None = None
    signature: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SandboxSessionResponse(BaseModel):
    """Project-scoped representation returned by the S0 session API."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    project_id: str
    mode: SandboxMode
    entrypoint: SandboxEntrypoint
    source_resource_id: str | None
    title: str
    initial_question: str | None
    status: SandboxSessionStatus
    creator_id: str
    context_snapshot_id: str | None = None
    context_hash: str | None = None
    created_at: datetime
    updated_at: datetime


class SandboxSessionStatusHistory(BaseModel):
    model_config = ConfigDict(frozen=True)

    history_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    project_id: str
    from_status: SandboxSessionStatus | None = None
    to_status: SandboxSessionStatus
    changed_by: str
    reason: str | None = Field(default=None, max_length=10_000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
