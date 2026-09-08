"""Question clarification, metadata-only plan generation, and review endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from sandbox_service.analysis_service import AnalysisPlanService
from sandbox_service.api.dependencies import (
    get_actor_context,
    get_actor_id,
    require_ai_enabled,
    require_data_analysis_enabled,
)
from sandbox_service.api.sessions import _http_error
from sandbox_service.api.openapi import SANDBOX_ERROR_RESPONSES
from sandbox_service.domain.analysis_plans import (
    AnalysisPlanDecision,
    AnalysisPlanVersion,
    AnalysisQuestionClarification,
    CreateAnalysisPlanRequest,
    CreateAnalysisQuestionRequest,
    ReviewAnalysisPlanRequest,
)
from sandbox_service.domain.datasets import AnalysisQuestion
from sandbox_service.domain.errors import SandboxDomainError

router = APIRouter(
    tags=["sandbox-analysis-plans"],
    dependencies=[Depends(require_data_analysis_enabled), Depends(get_actor_context)],
    responses=SANDBOX_ERROR_RESPONSES,
)


def get_analysis_plan_service(request: Request) -> AnalysisPlanService:
    return request.app.state.analysis_plan_service


@router.post(
    "/api/v1/projects/{project_id}/datasets/{dataset_id}/analysis-questions",
    response_model=AnalysisQuestion | AnalysisQuestionClarification,
    status_code=status.HTTP_201_CREATED,
)
async def create_analysis_question(
    http_request: Request,
    project_id: str,
    dataset_id: str,
    payload: CreateAnalysisQuestionRequest,
    service: Annotated[AnalysisPlanService, Depends(get_analysis_plan_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> AnalysisQuestion | AnalysisQuestionClarification:
    try:
        needs_ai = (
            payload.objective.value == "compare"
            and (not payload.outcome_columns or not payload.group_columns)
        ) or (
            payload.objective.value in {"associate", "predict"}
            and (not payload.outcome_columns or not payload.predictor_columns)
        )
        if needs_ai:
            require_ai_enabled(http_request)
        return await service.clarify_question(
            project_id=project_id,
            dataset_id=dataset_id,
            actor_id=actor_id,
            request=payload,
            correlation_id=x_correlation_id,
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post(
    "/api/v1/projects/{project_id}/datasets/{dataset_id}/analysis-plans",
    response_model=AnalysisPlanVersion,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_ai_enabled)],
)
async def create_analysis_plan(
    project_id: str,
    dataset_id: str,
    payload: CreateAnalysisPlanRequest,
    service: Annotated[AnalysisPlanService, Depends(get_analysis_plan_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> AnalysisPlanVersion:
    try:
        return await service.create_plan(
            project_id=project_id,
            dataset_id=dataset_id,
            actor_id=actor_id,
            request=payload,
            correlation_id=x_correlation_id,
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/api/v1/projects/{project_id}/analysis-plans/{plan_id}/versions/{version}",
    response_model=AnalysisPlanVersion,
)
async def get_analysis_plan(
    project_id: str,
    plan_id: str,
    version: int,
    service: Annotated[AnalysisPlanService, Depends(get_analysis_plan_service)],
) -> AnalysisPlanVersion:
    try:
        return await service.get_plan(project_id=project_id, plan_id=plan_id, version=version)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post(
    "/api/v1/projects/{project_id}/analysis-plans/{plan_id}/versions/{version}/review",
    response_model=AnalysisPlanDecision,
)
async def review_analysis_plan(
    project_id: str,
    plan_id: str,
    version: int,
    payload: ReviewAnalysisPlanRequest,
    service: Annotated[AnalysisPlanService, Depends(get_analysis_plan_service)],
    actor_id: Annotated[str, Depends(get_actor_id)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
) -> AnalysisPlanDecision:
    try:
        _, decision = await service.review_plan(
            project_id=project_id,
            plan_id=plan_id,
            version=version,
            reviewer_id=actor_id,
            idempotency_key=idempotency_key,
            request=payload,
        )
        return decision
    except SandboxDomainError as error:
        raise _http_error(error) from error
