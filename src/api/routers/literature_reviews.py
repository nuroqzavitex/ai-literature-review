from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status

from src.agents.litreview.application.jobs import LitReviewJobService
from src.agents.litreview.infrastructure.repositories.jobs import JobRepository
from src.config import get_settings
from src.models.schemas.literature_reviews import (
    AgentStatusResponse,
    EvaluationRequest,
    EvaluationResponse,
    JobListItem,
    JobStartResponse,
    JobStatus,
    JobStatusResponse,
    LitReviewRequest,
    LitReviewResultResponse,
    MVPMetricsResponse,
    PaperResponse,
    ReviewRequest,
    ReviewResponse,
    SelectedPapersIndexResponse,
    SelectedPapersQueryRequest,
    SelectedPapersQueryResponse,
    SelectedPapersRequest,
    WorkflowResumeRequest,
)
from src.services.llm import get_llm_route_status
from src.services.redis_jobs import get_job_notifier
from src.services.vector_store import QdrantVectorStore, VectorStoreError

router = APIRouter()
repository = JobRepository(initialize=False)
job_service = LitReviewJobService(repository)
STRUCTURED_RESULT_FIELDS = {
    "papers",
    "claims",
    "evidence_rows",
    "themes",
    "potential_gaps",
    "references",
    "decision_trace",
}


@router.get("/health")
async def api_health() -> dict[str, str]:
    return {"status": "ok", "service": "litreview-agent"}


@router.get("/status", response_model=AgentStatusResponse)
async def agent_status() -> AgentStatusResponse:
    try:
        providers = get_llm_route_status()
        return AgentStatusResponse(
            status="configured",
            agent="LitReview LangGraph MVP",
            providers=providers,
            failover_enabled=get_settings().llm_failover_enabled,
            runtime_verified=False,
            detail=(
                "Provider configuration is complete. Runtime quota and connectivity "
                "are verified only when a review invokes the provider."
            ),
        )
    except ValueError as exc:
        return AgentStatusResponse(
            status="misconfigured",
            agent="LitReview LangGraph MVP",
            providers=[],
            failover_enabled=get_settings().llm_failover_enabled,
            runtime_verified=False,
            detail=str(exc),
        )


@router.post(
    "/reviews",
    response_model=JobStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_lit_review(
    request: LitReviewRequest,
    http_request: Request,
) -> JobStartResponse:
    if request.role != "researcher":
        raise HTTPException(status_code=403, detail="Only researchers can create review jobs")
    job_id = f"job_{uuid4().hex}"
    repository.create_job(
        job_id,
        request.user_id,
        request.role,
        request.topic,
        request.max_results,
        request.execution_mode,
        response_language=request.response_language,
        request_id=getattr(http_request.state, "request_id", None),
    )
    # API only enqueues durable work.  The embedded or external worker claims
    # it with a PostgreSQL lease, so API restarts cannot orphan an in-memory task.
    await get_job_notifier().notify(job_id, "run")
    return JobStartResponse(job_id=job_id, thread_id=job_id, status="queued")


@router.get("/reviews", response_model=list[JobListItem])
async def list_lit_reviews(
    role: str = Query(...),
    limit: int = Query(default=50, ge=1, le=100),
    job_status: JobStatus | None = Query(default=None, alias="status"),
) -> list[JobListItem]:
    if role != "reviewer":
        raise HTTPException(status_code=403, detail="Reviewer role required")
    return [JobListItem.model_validate(item) for item in repository.list_jobs(limit, status_filter=job_status)]


@router.get("/reviews/{job_id}/status", response_model=JobStatusResponse)
async def lit_review_status(job_id: str) -> JobStatusResponse:
    current = repository.get_status(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse.model_validate(current)


@router.post("/reviews/{job_id}/resume", status_code=status.HTTP_202_ACCEPTED)
async def resume_workflow(job_id: str, request: WorkflowResumeRequest) -> dict[str, str]:
    current = repository.get_status(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if current["status"] != "hitl_waiting":
        raise HTTPException(status_code=409, detail="Workflow is not waiting for your decision")
    if current.get("hitl_stage") != request.stage:
        raise HTTPException(status_code=409, detail="This decision does not match the current workflow stage")
    if request.stage == "subqueries" and not request.sub_queries:
        raise HTTPException(status_code=422, detail="Cần ít nhất một sub-query")
    if request.stage == "papers" and request.mode == "manual" and not request.selected_paper_ids:
        raise HTTPException(status_code=422, detail="Hãy chọn ít nhất một bài báo")
    if not repository.resume_workflow(job_id, request.model_dump()):
        raise HTTPException(status_code=409, detail="Workflow could not be resumed")
    await get_job_notifier().notify(job_id, "resume")
    return {"job_id": job_id, "status": "resuming"}


@router.get("/reviews/{job_id}", response_model=LitReviewResultResponse)
async def lit_review_result(job_id: str) -> LitReviewResultResponse:
    current = repository.get_status(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if current["status"] in {"queued", "running", "resuming"}:
        raise HTTPException(status_code=409, detail="Job is still running")
    if current["status"] == "error":
        raise HTTPException(status_code=422, detail=current["error"])
    result = repository.get_result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not found")
    if not STRUCTURED_RESULT_FIELDS.issubset(result):
        raise HTTPException(
            status_code=409,
            detail="Legacy Markdown report is no longer supported; rerun this review",
        )
    return LitReviewResultResponse.model_validate(result)


@router.post(
    "/reviews/{job_id}/selected-papers/index",
    response_model=SelectedPapersIndexResponse,
)
async def index_selected_papers(
    job_id: str,
    request: SelectedPapersRequest,
) -> SelectedPapersIndexResponse:
    status_snapshot = repository.get_status(job_id)
    if status_snapshot is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not request.papers:
        raise HTTPException(status_code=422, detail="At least one paper is required")

    try:
        vector_store = QdrantVectorStore(backend=status_snapshot.get("embedding_backend") or "primary")
        indexed = await vector_store.index_selected_papers(
            [paper.model_dump(mode="json") for paper in request.papers],
            job_id,
            replace_existing=request.replace_existing,
        )
    except VectorStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return SelectedPapersIndexResponse(
        job_id=job_id,
        indexed_papers=indexed,
        replace_existing=request.replace_existing,
        collection=vector_store.collection,
    )


@router.post(
    "/reviews/{job_id}/selected-papers/query",
    response_model=SelectedPapersQueryResponse,
)
async def query_selected_papers(
    job_id: str,
    request: SelectedPapersQueryRequest,
) -> SelectedPapersQueryResponse:
    status_snapshot = repository.get_status(job_id)
    if status_snapshot is None:
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        results = await QdrantVectorStore(
            backend=status_snapshot.get("embedding_backend") or "primary"
        ).query_selected_papers(request.query, job_id, request.limit)
    except VectorStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return SelectedPapersQueryResponse(
        job_id=job_id,
        query=request.query,
        limit=request.limit,
        results=[PaperResponse.model_validate(paper) for paper in results],
    )


@router.post("/reviews/{job_id}/review", response_model=ReviewResponse, status_code=202)
async def review_lit_review(
    job_id: str,
    request: ReviewRequest,
) -> ReviewResponse:
    if request.role != "reviewer":
        raise HTTPException(status_code=403, detail="Reviewer role required")

    current = repository.get_status(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Job not found")
    result = repository.get_result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Completed report not found")
    if not STRUCTURED_RESULT_FIELDS.issubset(result):
        raise HTTPException(
            status_code=409,
            detail="Legacy Markdown report is no longer supported; rerun this review",
        )
    is_research_gap = result.get("workflow_type") == "research_gap"
    allowed_statuses = {"hitl_waiting", "approved"} if is_research_gap else {"hitl_waiting"}
    if current["status"] not in allowed_statuses:
        raise HTTPException(status_code=409, detail="Report is not waiting for review")
    if is_research_gap and request.report_decision == "request_changes":
        raise HTTPException(
            status_code=409,
            detail="Research-gap reports cannot resume a Lit Review checkpoint; start a new targeted gap search instead.",
        )

    claim_ids = {claim["claim_id"] for claim in result["claims"]}
    reviewed_claim_ids = {decision.claim_id for decision in request.decisions}
    if len(reviewed_claim_ids) != len(request.decisions):
        raise HTTPException(status_code=422, detail="Each claim may only be reviewed once")
    unknown_claim_ids = reviewed_claim_ids - claim_ids
    if unknown_claim_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown claim IDs: {sorted(unknown_claim_ids)}",
        )

    paper_ids = {reference["paper_id"] for reference in result["references"]}
    checked_paper_ids = {check.paper_id for check in request.reference_checks}
    if len(checked_paper_ids) != len(request.reference_checks):
        raise HTTPException(status_code=422, detail="Each reference may only be checked once")
    unknown_paper_ids = checked_paper_ids - paper_ids
    if unknown_paper_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown paper IDs: {sorted(unknown_paper_ids)}",
        )

    if request.report_decision == "approve":
        missing_claim_ids = claim_ids - reviewed_claim_ids
        missing_paper_ids = paper_ids - checked_paper_ids
        if missing_claim_ids or missing_paper_ids:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Approve requires every claim and reference to be reviewed",
                    "missing_claim_ids": sorted(missing_claim_ids),
                    "missing_paper_ids": sorted(missing_paper_ids),
                },
            )

    if request.report_decision == "request_changes":
        unsupported = [d for d in request.decisions if d.verdict == "unsupported"]
        if not unsupported:
            raise HTTPException(
                status_code=422,
                detail=(
                    "request_changes requires at least one claim marked as 'unsupported'. "
                    "If you want to request report-level changes without revising specific claims, "
                    "please annotate the relevant claim(s) as unsupported first."
                ),
            )

    saved = repository.save_review(
        job_id=job_id,
        reviewer_id=request.reviewer_id,
        decisions=[decision.model_dump() for decision in request.decisions],
        reference_checks=[check.model_dump() for check in request.reference_checks],
        report_decision=request.report_decision,
        report_note=request.report_note,
        resume_workflow=not is_research_gap,
    )
    if saved is None:
        raise HTTPException(status_code=404, detail="Completed report not found")

    if not is_research_gap:
        # The worker will claim this durable ``resuming`` row and restore the
        # LangGraph checkpoint; do not attach execution to the HTTP process.
        await get_job_notifier().notify(job_id, "resume")
    return ReviewResponse.model_validate(saved)


@router.post("/reviews/{job_id}/evaluation", response_model=EvaluationResponse)
async def submit_evaluation(
    job_id: str,
    request: EvaluationRequest,
) -> EvaluationResponse:
    current = repository.get_status(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if current["status"] != "approved":
        raise HTTPException(
            status_code=409,
            detail="Evaluations can only be submitted for approved jobs",
        )
    saved = repository.save_evaluation(
        job_id=job_id,
        evaluator_id=request.evaluator_id,
        manual_minutes=request.manual_minutes,
        mvp_minutes=request.mvp_minutes,
        usefulness_score=request.usefulness_score,
        notes=request.notes,
    )
    if saved is None:
        raise HTTPException(status_code=422, detail="Job is not approved or has no completed review")
    return EvaluationResponse.model_validate(saved)


@router.get("/reviews/{job_id}/evaluation", response_model=EvaluationResponse)
async def get_evaluation(job_id: str) -> EvaluationResponse:
    current = repository.get_status(job_id)
    if current is None:
        raise HTTPException(status_code=404, detail="Job not found")
    evaluation = repository.get_evaluation(job_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return EvaluationResponse.model_validate(evaluation)


@router.get("/metrics/mvp", response_model=MVPMetricsResponse)
async def get_mvp_metrics() -> MVPMetricsResponse:
    metrics = repository.get_mvp_metrics()
    return MVPMetricsResponse.model_validate(metrics)
