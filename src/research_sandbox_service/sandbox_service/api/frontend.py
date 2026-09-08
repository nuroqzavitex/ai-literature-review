"""Stable read/download endpoints required by the product frontend."""

from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from sandbox_service.api.dependencies import (
    get_actor_context,
    get_sandbox_settings,
    require_data_analysis_enabled,
    require_result_interpretation_enabled,
)
from sandbox_service.api.sessions import _http_error
from sandbox_service.api.openapi import SANDBOX_ERROR_RESPONSES
from sandbox_service.domain.analysis_plans import AnalysisPlanDecision, AnalysisPlanVersion
from sandbox_service.domain.datasets import AnalysisQuestion
from sandbox_service.domain.errors import SandboxDomainError
from sandbox_service.domain.execution import SandboxRunStatusHistory
from sandbox_service.domain.frontend import SandboxCapabilitiesResponse, SandboxModeCapabilities
from sandbox_service.domain.results import (
    AnalysisCitation,
    AnalysisResultInterpretationRecord,
    AnalysisResultValidation,
)
from sandbox_service.frontend_service import FrontendQueryService


router = APIRouter(
    prefix="/api/v1",
    tags=["sandbox-frontend"],
    responses=SANDBOX_ERROR_RESPONSES,
)
data_read_dependencies = [Depends(require_data_analysis_enabled), Depends(get_actor_context)]


def get_frontend_query_service(request: Request) -> FrontendQueryService:
    return request.app.state.frontend_query_service


@router.get("/sandbox/capabilities", response_model=SandboxCapabilitiesResponse)
async def get_sandbox_capabilities(request: Request) -> SandboxCapabilitiesResponse:
    settings = get_sandbox_settings(request)
    return SandboxCapabilitiesResponse(
        enabled=settings.enabled,
        modes=SandboxModeCapabilities(
            hypothesis=settings.allows_mode("hypothesis"),
            graph_overlay=settings.allows_mode("graph_overlay"),
            data_analysis=settings.allows_mode("data_analysis"),
        ),
        ai_enabled=settings.enabled and settings.ai_enabled,
        graph_context_enabled=settings.enabled and settings.graph_context_enabled,
        result_interpretation_enabled=(
            settings.enabled and settings.ai_enabled and settings.result_interpretation_enabled
        ),
    )


@router.get(
    "/projects/{project_id}/datasets/{dataset_id}/analysis-questions",
    response_model=list[AnalysisQuestion],
    dependencies=data_read_dependencies,
)
async def list_analysis_questions(
    project_id: str,
    dataset_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> list[AnalysisQuestion]:
    try:
        return await service.list_questions(project_id=project_id, dataset_id=dataset_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/projects/{project_id}/datasets/{dataset_id}/analysis-questions/{question_id}",
    response_model=AnalysisQuestion,
    dependencies=data_read_dependencies,
)
async def get_analysis_question(
    project_id: str,
    dataset_id: str,
    question_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> AnalysisQuestion:
    try:
        return await service.get_question(
            project_id=project_id, dataset_id=dataset_id, question_id=question_id
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/projects/{project_id}/datasets/{dataset_id}/analysis-plans",
    response_model=list[AnalysisPlanVersion],
    dependencies=data_read_dependencies,
)
async def list_dataset_analysis_plans(
    project_id: str,
    dataset_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> list[AnalysisPlanVersion]:
    try:
        return await service.list_dataset_plans(project_id=project_id, dataset_id=dataset_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/projects/{project_id}/analysis-plans/{plan_id}/versions",
    response_model=list[AnalysisPlanVersion],
    dependencies=data_read_dependencies,
)
async def list_analysis_plan_versions(
    project_id: str,
    plan_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> list[AnalysisPlanVersion]:
    try:
        return await service.list_plan_versions(project_id=project_id, plan_id=plan_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/projects/{project_id}/analysis-plans/{plan_id}/versions/{version}/decisions",
    response_model=list[AnalysisPlanDecision],
    dependencies=data_read_dependencies,
)
async def list_analysis_plan_decisions(
    project_id: str,
    plan_id: str,
    version: int,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> list[AnalysisPlanDecision]:
    try:
        return await service.list_plan_decisions(
            project_id=project_id, plan_id=plan_id, version=version
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/projects/{project_id}/sandbox-runs/{run_id}/status-history",
    response_model=list[SandboxRunStatusHistory],
    dependencies=data_read_dependencies,
)
async def list_sandbox_run_status_history(
    project_id: str,
    run_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> list[SandboxRunStatusHistory]:
    try:
        return await service.list_run_status_history(project_id=project_id, run_id=run_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/projects/{project_id}/sandbox-runs/{run_id}/validation",
    response_model=AnalysisResultValidation,
    dependencies=data_read_dependencies,
)
async def get_result_validation(
    project_id: str,
    run_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> AnalysisResultValidation:
    try:
        return await service.get_validation(project_id=project_id, run_id=run_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/projects/{project_id}/sandbox-runs/{run_id}/interpretation",
    response_model=AnalysisResultInterpretationRecord,
    dependencies=[
        Depends(require_data_analysis_enabled),
        Depends(require_result_interpretation_enabled),
        Depends(get_actor_context),
    ],
)
async def get_result_interpretation(
    project_id: str,
    run_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> AnalysisResultInterpretationRecord:
    try:
        return await service.get_interpretation(project_id=project_id, run_id=run_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/projects/{project_id}/sandbox-runs/{run_id}/citations",
    response_model=list[AnalysisCitation],
    dependencies=data_read_dependencies,
)
async def list_result_citations(
    project_id: str,
    run_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> list[AnalysisCitation]:
    try:
        return await service.list_citations(project_id=project_id, run_id=run_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/projects/{project_id}/sandbox-runs/{run_id}/artifacts/{artifact_id}/content",
    response_class=Response,
    dependencies=data_read_dependencies,
)
async def download_run_artifact(
    project_id: str,
    run_id: str,
    artifact_id: str,
    service: Annotated[FrontendQueryService, Depends(get_frontend_query_service)],
) -> Response:
    try:
        artifact, content = await service.get_artifact_content(
            project_id=project_id, run_id=run_id, artifact_id=artifact_id
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error
    media_type = {
        "result": "application/json",
        "table": "text/csv; charset=utf-8",
        "chart": "image/png",
        "diagnostic": "application/json",
    }[artifact.artifact_type]
    safe_name = PurePosixPath(artifact.filename).name.replace('"', "")
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "ETag": f'"{artifact.content_hash}"',
        },
    )
