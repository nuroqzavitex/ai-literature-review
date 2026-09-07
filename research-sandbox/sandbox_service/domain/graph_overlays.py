"""Read-only graph-overlay contracts. Base graph content is never persisted here."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OverlayStatus(StrEnum):
    DRAFT = "draft"
    ASSESSED = "assessed"
    STALE = "stale"
    DISCARDED = "discarded"


class OverlayOperationType(StrEnum):
    ADD_ENTITY = "add_entity"
    ADD_EDGE = "add_edge"
    REMOVE_EDGE = "remove_edge"
    REPLACE_PROPERTY = "replace_property"


class CreateGraphOverlayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    base_graph_version_id: str = Field(min_length=1, max_length=255)
    shared_graph_version_id: str | None = Field(default=None, max_length=255)


class GraphOverlay(BaseModel):
    model_config = ConfigDict(frozen=True)

    overlay_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    session_id: str
    base_graph_version_id: str
    shared_graph_version_id: str | None = None
    base_snapshot_hash: str | None = None
    operation_hash: str = Field(default="")
    status: OverlayStatus = OverlayStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreateGraphOverlayOperationRequest(BaseModel):
    """User input does not accept operation IDs or a non-hypothetical flag."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    operation: OverlayOperationType
    entity_or_edge_type: str = Field(min_length=1, max_length=255)
    source_ref: str | None = Field(default=None, max_length=255)
    target_ref: str | None = Field(default=None, max_length=255)
    proposed_properties: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1, max_length=10_000)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> "CreateGraphOverlayOperationRequest":
        if self.operation is OverlayOperationType.ADD_ENTITY and self.target_ref:
            raise ValueError("add_entity cannot specify target_ref")
        if self.operation in {OverlayOperationType.ADD_EDGE, OverlayOperationType.REMOVE_EDGE}:
            if not self.source_ref or not self.target_ref:
                raise ValueError("edge operations require source_ref and target_ref")
        if self.operation is OverlayOperationType.REPLACE_PROPERTY and not self.source_ref:
            raise ValueError("replace_property requires source_ref")
        return self


class GraphOverlayOperation(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation_id: str = Field(default_factory=lambda: str(uuid4()))
    overlay_id: str
    sequence: int = Field(ge=1)
    operation: OverlayOperationType
    entity_or_edge_type: str
    source_ref: str | None = None
    target_ref: str | None = None
    proposed_properties: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)
    hypothetical: Literal[True] = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OverlayAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    assessment_id: str = Field(default_factory=lambda: str(uuid4()))
    overlay_id: str
    base_graph_version_id: str
    operation_hash: str
    newly_reachable_paths: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    missing_evidence: list[dict[str, Any]] = Field(default_factory=list)
    compatibility_warnings: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: OverlayStatus = OverlayStatus.ASSESSED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OverlayComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    overlay: GraphOverlay
    assessment: OverlayAssessment | None
    operations: list[GraphOverlayOperation]
