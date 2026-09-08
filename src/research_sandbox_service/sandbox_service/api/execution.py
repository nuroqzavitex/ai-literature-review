"""Project-scoped run confirmation, lookup, cancellation, and artifact endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from sandbox_service.analysis_graph import AnalysisGraph
from sandbox_service.api.dependencies import (
    get_actor_context,
    get_actor_id,
    require_ai_enabled,
    require_data_analysis_enabled,
)
from sandbox_service.api.frontend import get_frontend_query_service
from sandbox_service.api.openapi import SANDBOX_ERROR_RESPONSES
from sandbox_service.api.sessions import _http_error
from sandbox_service.domain.errors import SandboxDomainError
from sandbox_service.domain.execution import CreateSandboxRunRequest, QueuedRunResponse
from sandbox_service.domain.frontend import AnalysisArtifactSummary, PublicAnalysisCode, PublicSandboxRun
from sandbox_service.execution_service import ExecutionService
from sandbox_service.frontend_service import FrontendQueryService

router = APIRouter(
    tags=["sandbox-runs"],
    dependencies=[Depends(require_data_analysis_enabled), Depends(get_actor_context)],
    responses=SANDBOX_ERROR_RESPONSES,
)


def get_analysis_graph(request: Request) -> AnalysisGraph:
    return request.app.state.analysis_graph


def get_execution_service(request: Request) -> ExecutionService:
    return request.app.state.execution_service


@router.get(
    "/api/v1/projects/{project_id}/analysis-plans/{plan_id}/versions/{version}/runs",
    response_model=list[PublicSandboxRun],
)
async def list_sandbox_runs(
    project_id: str,
    plan_id: str,
    version: int,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> list[PublicSandboxRun]:
    try:
        runs = await service.list_runs(
            project_id=project_id, plan_id=plan_id, plan_version=version
        )
        return [PublicSandboxRun.from_domain(run) for run in runs]
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post(
    "/api/v1/projects/{project_id}/analysis-plans/{plan_id}/versions/{version}/runs",
    response_model=QueuedRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_ai_enabled)],
)
async def create_sandbox_run(
    project_id: str,
    plan_id: str,
    version: int,
    payload: CreateSandboxRunRequest,
    graph: Annotated[AnalysisGraph, Depends(get_analysis_graph)],
    actor_id: Annotated[str, Depends(get_actor_id)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> QueuedRunResponse:
    try:
        run = await graph.confirm_execution(
            project_id=project_id,
            plan_id=plan_id,
            plan_version=version,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request=payload,
            correlation_id=x_correlation_id,
        )
        return ExecutionService.queued_response(run)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get("/api/v1/projects/{project_id}/sandbox-runs/{run_id}", response_model=PublicSandboxRun)
async def get_sandbox_run(
    project_id: str,
    run_id: str,
    service: Annotated[ExecutionService, Depends(get_execution_service)],
) -> PublicSandboxRun:
    try:
        return PublicSandboxRun.from_domain(
            await service.get_run(project_id=project_id, run_id=run_id)
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/api/v1/projects/{project_id}/sandbox-runs/{run_id}/code",
    response_model=PublicAnalysisCode,
)
async def get_sandbox_run_code(
    project_id: str,
    run_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> PublicAnalysisCode:
    try:
        return await service.get_run_code(project_id=project_id, run_id=run_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post("/api/v1/projects/{project_id}/sandbox-runs/{run_id}/cancel", response_model=PublicSandboxRun)
async def cancel_sandbox_run(
    project_id: str,
    run_id: str,
    service: Annotated[ExecutionService, Depends(get_execution_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> PublicSandboxRun:
    try:
        return PublicSandboxRun.from_domain(
            await service.cancel_run(project_id=project_id, run_id=run_id, actor_id=actor_id)
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/api/v1/projects/{project_id}/sandbox-runs/{run_id}/artifacts",
    response_model=list[AnalysisArtifactSummary],
)
async def list_sandbox_run_artifacts(
    project_id: str,
    run_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> list[AnalysisArtifactSummary]:
    try:
        return await service.list_artifacts(project_id=project_id, run_id=run_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error
