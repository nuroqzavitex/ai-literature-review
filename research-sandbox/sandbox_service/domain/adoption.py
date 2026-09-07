"""Draft-only hand-off contracts; Sandbox never publishes into a core graph."""

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AdoptionProposalStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class AdoptionSourceType(StrEnum):
    HYPOTHESIS = "hypothesis"
    OVERLAY_ASSESSMENT = "overlay_assessment"


class CreateAdoptionProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_type: AdoptionSourceType
    source_id: str = Field(min_length=1, max_length=255)
    rationale: str = Field(min_length=1, max_length=10_000)


class ReviewAdoptionProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: AdoptionProposalStatus
    reason: str | None = Field(default=None, max_length=10_000)


class AdoptionProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    session_id: str
    source_type: AdoptionSourceType
    source_id: str
    rationale: str
    status: AdoptionProposalStatus = AdoptionProposalStatus.DRAFT
    requested_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AdoptionDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    proposal_id: str
    reviewer_id: str
    decision: AdoptionProposalStatus
    reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
