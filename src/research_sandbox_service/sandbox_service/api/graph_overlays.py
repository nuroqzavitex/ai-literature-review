"""Project-scoped, read-only graph-overlay endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from sandbox_service.api.dependencies import (
    get_actor_context,
    get_actor_id,
    require_graph_overlay_enabled,
)
from sandbox_service.api.openapi import SANDBOX_ERROR_RESPONSES
from sandbox_service.api.sessions import _http_error
from sandbox_service.domain.errors import SandboxDomainError
from sandbox_service.domain.graph_overlays import (
    CreateGraphOverlayOperationRequest,
    CreateGraphOverlayRequest,
    GraphOverlay,
    GraphOverlayOperation,
    OverlayAssessment,
    OverlayComparison,
)
from sandbox_service.graph_overlay import GraphOverlaySandboxService

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/sandbox-sessions/{session_id}/graph-overlays",
    tags=["sandbox-graph-overlays"],
    dependencies=[Depends(require_graph_overlay_enabled), Depends(get_actor_context)],
    responses=SANDBOX_ERROR_RESPONSES,
)


def get_overlay_service(request: Request) -> GraphOverlaySandboxService:
    return request.app.state.graph_overlay_service


@router.get("", response_model=list[GraphOverlay])
async def list_overlays(
    project_id: str,
    session_id: str,
    service: Annotated[GraphOverlaySandboxService, Depends(get_overlay_service)],
) -> list[GraphOverlay]:
    try:
        return await service.list_overlays(project_id=project_id, session_id=session_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post("", response_model=GraphOverlay, status_code=status.HTTP_201_CREATED)
async def create_overlay(
    project_id: str,
    session_id: str,
    payload: CreateGraphOverlayRequest,
    service: Annotated[GraphOverlaySandboxService, Depends(get_overlay_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> GraphOverlay:
    try:
        return await service.create_overlay(
            project_id=project_id, session_id=session_id, actor_id=actor_id, request=payload
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post("/{overlay_id}/operations", response_model=GraphOverlayOperation, status_code=status.HTTP_201_CREATED)
async def add_overlay_operation(
    project_id: str,
    session_id: str,
    overlay_id: str,
    payload: CreateGraphOverlayOperationRequest,
    service: Annotated[GraphOverlaySandboxService, Depends(get_overlay_service)],
) -> GraphOverlayOperation:
    try:
        return await service.add_operation(
            project_id=project_id, session_id=session_id, overlay_id=overlay_id, request=payload
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post("/{overlay_id}/assess", response_model=OverlayAssessment)
async def assess_overlay(
    project_id: str,
    session_id: str,
    overlay_id: str,
    service: Annotated[GraphOverlaySandboxService, Depends(get_overlay_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> OverlayAssessment:
    try:
        return await service.assess(
            project_id=project_id, session_id=session_id, overlay_id=overlay_id, actor_id=actor_id
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get("/{overlay_id}", response_model=GraphOverlay)
async def get_overlay(
    project_id: str,
    session_id: str,
    overlay_id: str,
    service: Annotated[GraphOverlaySandboxService, Depends(get_overlay_service)],
) -> GraphOverlay:
    try:
        return (await service.get_comparison(
            project_id=project_id, session_id=session_id, overlay_id=overlay_id
        )).overlay
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get("/{overlay_id}/comparison", response_model=OverlayComparison)
async def get_overlay_comparison(
    project_id: str,
    session_id: str,
    overlay_id: str,
    service: Annotated[GraphOverlaySandboxService, Depends(get_overlay_service)],
) -> OverlayComparison:
    try:
        return await service.get_comparison(
            project_id=project_id, session_id=session_id, overlay_id=overlay_id
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error
