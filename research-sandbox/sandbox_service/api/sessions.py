"""Project-scoped S0 session endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from sandbox_service.api.dependencies import (
    TrustedActorContext,
    ensure_mode_enabled,
    get_actor_context,
    get_actor_id,
    require_sandbox_enabled,
)
from sandbox_service.api.openapi import SANDBOX_ERROR_RESPONSES
from sandbox_service.domain.errors import SandboxDomainError
from sandbox_service.domain.sessions import (
    CreateSandboxSessionRequest,
    ResearchContextSnapshot,
    SandboxSessionResponse,
    SandboxSessionStatusHistory,
)
from sandbox_service.session_service import SandboxSessionService

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/sandbox-sessions",
    tags=["sandbox-sessions"],
    dependencies=[Depends(require_sandbox_enabled), Depends(get_actor_context)],
    responses=SANDBOX_ERROR_RESPONSES,
)


def get_session_service(request: Request) -> SandboxSessionService:
    return request.app.state.sandbox_session_service


def _http_error(error: SandboxDomainError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={
            "error_code": error.error_code,
            "message": str(error),
            "retryable": False,
            "details": error.details,
        },
    )


@router.post("", response_model=SandboxSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_sandbox_session(
    request: Request,
    project_id: str,
    payload: CreateSandboxSessionRequest,
    service: Annotated[SandboxSessionService, Depends(get_session_service)],
    actor: Annotated[TrustedActorContext, Depends(get_actor_context)],
) -> SandboxSessionResponse:
    try:
        ensure_mode_enabled(request, payload.mode)
        return await service.create_session(
            project_id=project_id,
            request=payload,
            actor_id=actor.actor_id,
            correlation_id=actor.correlation_id,
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get("", response_model=list[SandboxSessionResponse])
async def list_sandbox_sessions(
    project_id: str,
    service: Annotated[SandboxSessionService, Depends(get_session_service)],
) -> list[SandboxSessionResponse]:
    return await service.list_sessions(project_id=project_id)


@router.get("/{session_id}", response_model=SandboxSessionResponse)
async def get_sandbox_session(
    project_id: str,
    session_id: str,
    service: Annotated[SandboxSessionService, Depends(get_session_service)],
) -> SandboxSessionResponse:
    try:
        return await service.get_session(project_id=project_id, session_id=session_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get("/{session_id}/context", response_model=ResearchContextSnapshot | None)
async def get_sandbox_session_context(
    project_id: str,
    session_id: str,
    service: Annotated[SandboxSessionService, Depends(get_session_service)],
) -> ResearchContextSnapshot | None:
    try:
        return await service.get_session_context(
            project_id=project_id, session_id=session_id
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post("/{session_id}/close", response_model=SandboxSessionResponse)
async def close_sandbox_session(
    project_id: str,
    session_id: str,
    service: Annotated[SandboxSessionService, Depends(get_session_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> SandboxSessionResponse:
    try:
        return await service.close_session(
            project_id=project_id, session_id=session_id, actor_id=actor_id
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post("/{session_id}/discard", response_model=SandboxSessionResponse)
async def discard_sandbox_session(
    project_id: str,
    session_id: str,
    service: Annotated[SandboxSessionService, Depends(get_session_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> SandboxSessionResponse:
    try:
        return await service.discard_session(
            project_id=project_id, session_id=session_id, actor_id=actor_id
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/{session_id}/status-history",
    response_model=list[SandboxSessionStatusHistory],
)
async def list_sandbox_session_status_history(
    project_id: str,
    session_id: str,
    service: Annotated[SandboxSessionService, Depends(get_session_service)],
) -> list[SandboxSessionStatusHistory]:
    try:
        return await service.list_status_history(project_id=project_id, session_id=session_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error
