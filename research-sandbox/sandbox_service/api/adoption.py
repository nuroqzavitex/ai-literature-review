"""Adoption proposal endpoints; these never publish to a base graph."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from sandbox_service.adoption import AdoptionProposalService
from sandbox_service.api.dependencies import (
    TrustedActorContext,
    get_actor_context,
    get_actor_id,
    require_sandbox_enabled,
)
from sandbox_service.api.sessions import _http_error
from sandbox_service.api.openapi import SANDBOX_ERROR_RESPONSES
from sandbox_service.domain.adoption import (
    AdoptionProposal,
    CreateAdoptionProposalRequest,
    ReviewAdoptionProposalRequest,
)
from sandbox_service.domain.errors import SandboxDomainError
from sandbox_service.domain.frontend import AdoptionHandOffResponse
from sandbox_service.integration.adoption_bridge import AdoptionHandOffRejected, AdoptionProposalBridge

router = APIRouter(
    tags=["sandbox-adoption-proposals"],
    dependencies=[Depends(require_sandbox_enabled), Depends(get_actor_context)],
    responses=SANDBOX_ERROR_RESPONSES,
)


def get_adoption_service(request: Request) -> AdoptionProposalService:
    return request.app.state.adoption_proposal_service


def get_adoption_bridge(request: Request) -> AdoptionProposalBridge:
    bridge = getattr(request.app.state, "adoption_proposal_bridge", None)
    if bridge is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "ADOPTION_HANDOFF_UNAVAILABLE",
                "message": "Core adoption hand-off is not configured",
                "retryable": True,
                "details": {},
            },
        )
    return bridge


@router.post(
    "/api/v1/projects/{project_id}/sandbox-sessions/{session_id}/adoption-proposals",
    response_model=AdoptionProposal,
    status_code=status.HTTP_201_CREATED,
)
async def create_adoption_proposal(
    project_id: str,
    session_id: str,
    payload: CreateAdoptionProposalRequest,
    service: Annotated[AdoptionProposalService, Depends(get_adoption_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> AdoptionProposal:
    try:
        return await service.create(
            project_id=project_id, session_id=session_id, actor_id=actor_id, request=payload
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/api/v1/projects/{project_id}/sandbox-sessions/{session_id}/adoption-proposals",
    response_model=list[AdoptionProposal],
)
async def list_adoption_proposals(
    project_id: str,
    session_id: str,
    service: Annotated[AdoptionProposalService, Depends(get_adoption_service)],
) -> list[AdoptionProposal]:
    try:
        return await service.list(project_id=project_id, session_id=session_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/api/v1/projects/{project_id}/sandbox-adoption-proposals/{proposal_id}",
    response_model=AdoptionProposal,
)
async def get_adoption_proposal(
    project_id: str,
    proposal_id: str,
    service: Annotated[AdoptionProposalService, Depends(get_adoption_service)],
) -> AdoptionProposal:
    try:
        return await service.get(project_id=project_id, proposal_id=proposal_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post(
    "/api/v1/projects/{project_id}/sandbox-adoption-proposals/{proposal_id}/review",
    response_model=AdoptionProposal,
)
async def review_adoption_proposal(
    project_id: str,
    proposal_id: str,
    payload: ReviewAdoptionProposalRequest,
    service: Annotated[AdoptionProposalService, Depends(get_adoption_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> AdoptionProposal:
    try:
        return await service.review(
            project_id=project_id, proposal_id=proposal_id, reviewer_id=actor_id, request=payload
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post(
    "/api/v1/projects/{project_id}/sandbox-adoption-proposals/{proposal_id}/handoff",
    response_model=AdoptionHandOffResponse,
)
async def hand_off_adoption_proposal(
    project_id: str,
    proposal_id: str,
    service: Annotated[AdoptionProposalService, Depends(get_adoption_service)],
    bridge: Annotated[AdoptionProposalBridge, Depends(get_adoption_bridge)],
    actor: Annotated[TrustedActorContext, Depends(get_actor_context)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> AdoptionHandOffResponse:
    try:
        proposal = await service.get(project_id=project_id, proposal_id=proposal_id)
        source_bundle = await service.handoff_bundle(
            project_id=project_id, proposal=proposal
        )
        core_draft_id = await bridge.hand_off(
            project_id=project_id,
            actor_id=actor.actor_id,
            correlation_id=actor.correlation_id,
            proposal=proposal,
            source_bundle=source_bundle,
            idempotency_key=idempotency_key,
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error
    except AdoptionHandOffRejected as error:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "ADOPTION_HANDOFF_REJECTED",
                "message": str(error),
                "retryable": False,
                "details": {},
            },
        ) from error
    response = AdoptionHandOffResponse(
        proposal_id=proposal_id,
        core_draft_id=core_draft_id,
    )
    return response
