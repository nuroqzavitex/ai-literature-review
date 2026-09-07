"""Adoption stays a proposal until an external core integration revalidates it."""

from datetime import datetime, timezone
from typing import Protocol

from sandbox_service.domain.adoption import (
    AdoptionDecision,
    AdoptionProposal,
    AdoptionProposalStatus,
    AdoptionSourceType,
    CreateAdoptionProposalRequest,
    ReviewAdoptionProposalRequest,
)
from sandbox_service.domain.errors import AdoptionReviewRequired, SandboxSessionNotFound
from sandbox_service.domain.graph_overlays import OverlayStatus
from sandbox_service.domain.hypotheses import DraftStatus
from sandbox_service.domain.sessions import SandboxSessionResponse, SandboxSessionStatus


class AdoptionRepository(Protocol):
    async def get_session(self, *, project_id: str, session_id: str) -> SandboxSessionResponse | None: ...

    async def get_hypothesis(self, *, project_id: str, session_id: str, hypothesis_id: str): ...

    async def get_assessment_by_id(self, *, assessment_id: str): ...

    async def get_overlay(self, *, project_id: str, session_id: str, overlay_id: str): ...

    async def list_overlay_operations(self, *, overlay_id: str): ...

    async def save_adoption_proposal(self, proposal: AdoptionProposal) -> AdoptionProposal: ...

    async def get_adoption_proposal(
        self, *, project_id: str, session_id: str, proposal_id: str
    ) -> AdoptionProposal | None: ...

    async def find_adoption_proposal(self, *, project_id: str, proposal_id: str) -> AdoptionProposal | None: ...

    async def list_adoption_proposals(
        self, *, project_id: str, session_id: str
    ) -> list[AdoptionProposal]: ...

    async def save_adoption_decision(self, decision: AdoptionDecision) -> AdoptionDecision: ...


class AdoptionProposalService:
    """S1 persists review state only; it never calls a core graph write adapter."""

    def __init__(self, *, repository: AdoptionRepository) -> None:
        self._repository = repository

    async def create(
        self,
        *,
        project_id: str,
        session_id: str,
        actor_id: str,
        request: CreateAdoptionProposalRequest,
    ) -> AdoptionProposal:
        session = await self._load_session(project_id=project_id, session_id=session_id)
        await self._validate_source(
            project_id=project_id, session_id=session_id, source_type=request.source_type, source_id=request.source_id
        )
        return await self._repository.save_adoption_proposal(
            AdoptionProposal(
                project_id=project_id,
                session_id=session_id,
                source_type=request.source_type,
                source_id=request.source_id,
                rationale=request.rationale,
                requested_by=actor_id,
            )
        )

    async def list(self, *, project_id: str, session_id: str) -> list[AdoptionProposal]:
        await self._load_session(project_id=project_id, session_id=session_id)
        return await self._repository.list_adoption_proposals(project_id=project_id, session_id=session_id)

    async def get(self, *, project_id: str, proposal_id: str) -> AdoptionProposal:
        proposal = await self._repository.find_adoption_proposal(
            project_id=project_id, proposal_id=proposal_id
        )
        if proposal is None:
            raise SandboxSessionNotFound("Adoption proposal was not found in this project")
        await self._load_session(project_id=project_id, session_id=proposal.session_id)
        return proposal

    async def review(
        self,
        *,
        project_id: str,
        proposal_id: str,
        reviewer_id: str,
        request: ReviewAdoptionProposalRequest,
    ) -> AdoptionProposal:
        proposal = await self._repository.find_adoption_proposal(
            project_id=project_id, proposal_id=proposal_id
        )
        if proposal is None:
            raise SandboxSessionNotFound("Adoption proposal was not found in this project")
        session = await self._load_session(project_id=project_id, session_id=proposal.session_id)
        if proposal.status not in {AdoptionProposalStatus.DRAFT, AdoptionProposalStatus.IN_REVIEW}:
            raise AdoptionReviewRequired("A terminal adoption proposal cannot be reviewed again")
        if request.decision not in {
            AdoptionProposalStatus.IN_REVIEW,
            AdoptionProposalStatus.APPROVED,
            AdoptionProposalStatus.REJECTED,
        }:
            raise AdoptionReviewRequired("Review action must start, approve, or reject the proposal")
        if request.decision is AdoptionProposalStatus.IN_REVIEW and proposal.status is not AdoptionProposalStatus.DRAFT:
            raise AdoptionReviewRequired("Only a draft proposal can enter review")
        if session.status is SandboxSessionStatus.STALE:
            raise AdoptionReviewRequired("A stale session cannot be approved for adoption")
        await self._validate_source(
            project_id=project_id, session_id=proposal.session_id, source_type=proposal.source_type, source_id=proposal.source_id
        )
        updated = proposal.model_copy(
            update={"status": request.decision, "updated_at": datetime.now(timezone.utc)}
        )
        await self._repository.save_adoption_proposal(updated)
        if request.decision in {AdoptionProposalStatus.APPROVED, AdoptionProposalStatus.REJECTED}:
            await self._repository.save_adoption_decision(
                AdoptionDecision(
                    proposal_id=proposal_id,
                    reviewer_id=reviewer_id,
                    decision=request.decision,
                    reason=request.reason,
                )
            )
        return updated

    async def handoff_bundle(
        self, *, project_id: str, proposal: AdoptionProposal
    ) -> dict:
        """Seal the exact reviewed source that the core backend will receive."""

        if proposal.project_id != project_id:
            raise SandboxSessionNotFound("Adoption proposal was not found in this project")
        if proposal.source_type is AdoptionSourceType.HYPOTHESIS:
            hypothesis = await self._repository.get_hypothesis(
                project_id=project_id,
                session_id=proposal.session_id,
                hypothesis_id=proposal.source_id,
            )
            if hypothesis is None or hypothesis.status is not DraftStatus.REVIEWED:
                raise AdoptionReviewRequired("Reviewed hypothesis source is no longer available")
            return {
                "schema_version": "sandbox_adoption_source.v1",
                "source_type": proposal.source_type.value,
                "base_graph_version_id": None,
                "hypothesis": hypothesis.model_dump(mode="json"),
            }
        assessment = await self._repository.get_assessment_by_id(
            assessment_id=proposal.source_id
        )
        if assessment is None:
            raise AdoptionReviewRequired("Assessed overlay source is no longer available")
        overlay = await self._repository.get_overlay(
            project_id=project_id,
            session_id=proposal.session_id,
            overlay_id=assessment.overlay_id,
        )
        if (
            overlay is None
            or overlay.status is not OverlayStatus.ASSESSED
            or overlay.operation_hash != assessment.operation_hash
        ):
            raise AdoptionReviewRequired("Overlay changed after assessment and must be assessed again")
        operations = await self._repository.list_overlay_operations(
            overlay_id=overlay.overlay_id
        )
        return {
            "schema_version": "sandbox_adoption_source.v1",
            "source_type": proposal.source_type.value,
            "base_graph_version_id": overlay.base_graph_version_id,
            "base_snapshot_hash": overlay.base_snapshot_hash,
            "overlay": overlay.model_dump(mode="json"),
            "assessment": assessment.model_dump(mode="json"),
            "operations": [item.model_dump(mode="json") for item in operations],
        }

    async def _load_session(self, *, project_id: str, session_id: str) -> SandboxSessionResponse:
        session = await self._repository.get_session(project_id=project_id, session_id=session_id)
        if session is None:
            raise SandboxSessionNotFound("Sandbox session was not found in this project")
        return session

    async def _validate_source(
        self, *, project_id: str, session_id: str, source_type: AdoptionSourceType, source_id: str
    ) -> None:
        if source_type is AdoptionSourceType.HYPOTHESIS:
            hypothesis = await self._repository.get_hypothesis(
                project_id=project_id, session_id=session_id, hypothesis_id=source_id
            )
            if hypothesis is None or hypothesis.status is not DraftStatus.REVIEWED:
                raise AdoptionReviewRequired("Only a reviewed hypothesis draft can be proposed for adoption")
            return
        assessment = await self._repository.get_assessment_by_id(assessment_id=source_id)
        if assessment is None or assessment.status is not OverlayStatus.ASSESSED:
            raise AdoptionReviewRequired("Only an assessed overlay can be proposed for adoption")
        overlay = await self._repository.get_overlay(
            project_id=project_id, session_id=session_id, overlay_id=assessment.overlay_id
        )
        if (
            overlay is None
            or overlay.status is not OverlayStatus.ASSESSED
            or overlay.operation_hash != assessment.operation_hash
        ):
            raise AdoptionReviewRequired("Overlay source is stale or out of project scope")
