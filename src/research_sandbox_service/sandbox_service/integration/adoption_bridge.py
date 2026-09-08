"""One-way hand-off of approved sandbox proposals as core-owned draft records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import hashlib

from sandbox_service.integration.auth import canonical_json

from sandbox_service.domain.adoption import AdoptionProposal, AdoptionProposalStatus


class AdoptionHandOffRejected(ValueError):
    pass


@dataclass(frozen=True)
class CoreDraftProposal:
    project_id: str
    source_system: str
    sandbox_proposal_id: str
    source_type: str
    source_id: str
    rationale: str
    base_graph_version_id: str | None
    source_hash: str
    source_bundle: dict[str, Any]
    status: str = "draft"


class CoreDraftProposalSink(Protocol):
    async def create_draft(
        self,
        proposal: CoreDraftProposal,
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> str: ...


class CoreAdoptionRevalidator(Protocol):
    async def is_current_and_authorized(
        self,
        *,
        project_id: str,
        proposal: AdoptionProposal,
        actor_id: str,
        source_bundle: dict[str, Any],
    ) -> bool: ...


class AdoptionProposalBridge:
    """Does not publish knowledge: an approved sandbox proposal becomes a core draft only."""

    def __init__(self, *, sink: CoreDraftProposalSink, revalidator: CoreAdoptionRevalidator) -> None:
        self._sink = sink
        self._revalidator = revalidator

    async def hand_off(
        self,
        *,
        project_id: str,
        actor_id: str,
        correlation_id: str,
        proposal: AdoptionProposal,
        source_bundle: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> str:
        if proposal.project_id != project_id:
            raise AdoptionHandOffRejected("approved adoption proposal is outside this project")
        if proposal.status is not AdoptionProposalStatus.APPROVED:
            raise AdoptionHandOffRejected("only reviewer-approved adoption proposals can be handed off")
        if not await self._revalidator.is_current_and_authorized(
            project_id=project_id,
            proposal=proposal,
            actor_id=actor_id,
            source_bundle=source_bundle,
        ):
            raise AdoptionHandOffRejected("core source version is stale or access is no longer authorized")
        source_hash = hashlib.sha256(canonical_json(source_bundle)).hexdigest()
        draft = CoreDraftProposal(
            project_id=project_id,
            source_system="research-sandbox",
            sandbox_proposal_id=proposal.proposal_id,
            source_type=proposal.source_type.value,
            source_id=proposal.source_id,
            rationale=proposal.rationale,
            base_graph_version_id=source_bundle.get("base_graph_version_id"),
            source_hash=source_hash,
            source_bundle=source_bundle,
        )
        if idempotency_key is None:
            # Backwards-compatible path for an existing core sink implementation.
            return await self._sink.create_draft(
                draft, actor_id=actor_id, correlation_id=correlation_id
            )
        return await self._sink.create_draft(
            draft,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
