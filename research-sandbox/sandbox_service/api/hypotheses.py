"""Project-scoped hypothesis and experiment draft endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status

from sandbox_service.api.dependencies import (
    get_actor_context,
    get_actor_id,
    require_ai_enabled,
    require_hypothesis_enabled,
)
from sandbox_service.api.sessions import _http_error
from sandbox_service.api.openapi import SANDBOX_ERROR_RESPONSES
from sandbox_service.domain.errors import SandboxDomainError
from sandbox_service.domain.hypotheses import (
    ExperimentDraft,
    GenerateExperimentRequest,
    GenerateHypothesisRequest,
    HypothesisDraft,
    ReviewHypothesisDraftRequest,
)
from sandbox_service.hypothesis_graph import HypothesisSandboxGraph

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/sandbox-sessions/{session_id}",
    tags=["sandbox-hypotheses"],
    dependencies=[Depends(require_hypothesis_enabled), Depends(get_actor_context)],
    responses=SANDBOX_ERROR_RESPONSES,
)


def get_hypothesis_graph(request: Request) -> HypothesisSandboxGraph:
    return request.app.state.hypothesis_sandbox_graph


@router.post(
    "/hypotheses",
    response_model=HypothesisDraft,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_ai_enabled)],
)
async def create_hypothesis(
    project_id: str,
    session_id: str,
    payload: GenerateHypothesisRequest,
    graph: Annotated[HypothesisSandboxGraph, Depends(get_hypothesis_graph)],
    actor_id: Annotated[str, Depends(get_actor_id)],
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> HypothesisDraft:
    try:
        return await graph.generate_hypothesis(
            project_id=project_id,
            session_id=session_id,
            actor_id=actor_id,
            question=payload.question,
            output_language=payload.output_language,
            correlation_id=x_correlation_id,
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get("/hypotheses", response_model=list[HypothesisDraft])
async def list_hypotheses(
    project_id: str,
    session_id: str,
    graph: Annotated[HypothesisSandboxGraph, Depends(get_hypothesis_graph)],
) -> list[HypothesisDraft]:
    try:
        return await graph.list_hypotheses(project_id=project_id, session_id=session_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post("/hypotheses/{hypothesis_id}/review", response_model=HypothesisDraft)
async def review_hypothesis(
    project_id: str,
    session_id: str,
    hypothesis_id: str,
    payload: ReviewHypothesisDraftRequest,
    graph: Annotated[HypothesisSandboxGraph, Depends(get_hypothesis_graph)],
    actor_id: Annotated[str, Depends(get_actor_id)],
) -> HypothesisDraft:
    try:
        return await graph.review_hypothesis(
            project_id=project_id,
            session_id=session_id,
            hypothesis_id=hypothesis_id,
            reviewer_id=actor_id,
            request=payload,
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.post(
    "/experiments",
    response_model=ExperimentDraft,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_ai_enabled)],
)
async def create_experiment(
    project_id: str,
    session_id: str,
    payload: GenerateExperimentRequest,
    graph: Annotated[HypothesisSandboxGraph, Depends(get_hypothesis_graph)],
    actor_id: Annotated[str, Depends(get_actor_id)],
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> ExperimentDraft:
    try:
        return await graph.generate_experiment(
            project_id=project_id,
            session_id=session_id,
            hypothesis_id=payload.hypothesis_id,
            actor_id=actor_id,
            output_language=payload.output_language,
            correlation_id=x_correlation_id,
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get("/experiments", response_model=list[ExperimentDraft])
async def list_experiments(
    project_id: str,
    session_id: str,
    graph: Annotated[HypothesisSandboxGraph, Depends(get_hypothesis_graph)],
) -> list[ExperimentDraft]:
    try:
        return await graph.list_experiments(project_id=project_id, session_id=session_id)
    except SandboxDomainError as error:
        raise _http_error(error) from error


@router.get("/experiments/{experiment_id}", response_model=ExperimentDraft)
async def get_experiment(
    project_id: str,
    session_id: str,
    experiment_id: str,
    graph: Annotated[HypothesisSandboxGraph, Depends(get_hypothesis_graph)],
) -> ExperimentDraft:
    try:
        return await graph.get_experiment(
            project_id=project_id, session_id=session_id, experiment_id=experiment_id
        )
    except SandboxDomainError as error:
        raise _http_error(error) from error
