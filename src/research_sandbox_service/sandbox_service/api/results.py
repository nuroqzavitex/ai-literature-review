"""Project-scoped result review and reproducibility bundle endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from sandbox_service.api.dependencies import (
    TrustedActorContext,
    get_actor_context,
    get_actor_id,
    require_data_analysis_enabled,
    require_result_interpretation_enabled,
)
from sandbox_service.api.openapi import SANDBOX_ERROR_RESPONSES
from sandbox_service.api.sessions import _http_error
from sandbox_service.domain.errors import SandboxDomainError
from sandbox_service.domain.results import (
    AnalysisReproducibilityBundle,
    AnalysisResultInterpretationRecord,
    ResultReviewResponse,
    ReviewAnalysisResultRequest,
)
from sandbox_service.result_service import ResultReviewService


router = APIRouter(
    tags=["sandbox-results"],
    dependencies=[Depends(require_data_analysis_enabled), Depends(get_actor_context)],
    responses=SANDBOX_ERROR_RESPONSES,
)


def get_result_review_service(request: Request) -> ResultReviewService:
    return request.app.state.result_review_service


@router.post(
    "/api/v1/projects/{project_id}/sandbox-runs/{run_id}/interpretation",
    response_model=AnalysisResultInterpretationRecord,
    dependencies=[Depends(require_result_interpretation_enabled)],
)
async def generate_result_interpretation(
    project_id: str,
    run_id: str,
    service: Annotated[ResultReviewService, Depends(get_result_review_service)],
    actor_context: Annotated[TrustedActorContext, Depends(get_actor_context)],
) -> AnalysisResultInterpretationRecord:
    try:
        interpretation, _ = await service.interpret_validated(
            project_id=project_id,
            run_id=run_id,
            correlation_id=actor_context.correlation_id,
        )
        return interpretation
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post(
    "/api/v1/projects/{project_id}/sandbox-runs/{run_id}/review",
    response_model=ResultReviewResponse,
)
async def review_sandbox_result(
    project_id: str,
    run_id: str,
    payload: ReviewAnalysisResultRequest,
    service: Annotated[ResultReviewService, Depends(get_result_review_service)],
    reviewer_id: Annotated[str, Depends(get_actor_id)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
) -> ResultReviewResponse:
    try:
        run, review = await service.review_result(
            project_id=project_id,
            run_id=run_id,
            reviewer_id=reviewer_id,
            idempotency_key=idempotency_key,
            request=payload,
        )
        return ResultReviewResponse(run_status=run.status.value, review=review)  # type: ignore[arg-type]
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get(
    "/api/v1/projects/{project_id}/sandbox-runs/{run_id}/reproducibility-bundle",
    response_model=AnalysisReproducibilityBundle,
)
async def get_reproducibility_bundle(
    project_id: str,
    run_id: str,
    service: Annotated[ResultReviewService, Depends(get_result_review_service)],
) -> AnalysisReproducibilityBundle:
    try:
        return await service.get_bundle(project_id=project_id, run_id=run_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error
