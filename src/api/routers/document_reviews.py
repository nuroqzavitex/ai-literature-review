from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from src.agents.document_review.application.service import (
    DocumentReviewConflictError,
    DocumentReviewError,
    DocumentReviewNotFoundError,
    DocumentReviewService,
)
from src.api.routers import research_copilot as copilot
from src.models.schemas.document_reviews import (
    AnnotationActionRequest,
    ApplyRewriteRequest,
    DocumentContentUpdateRequest,
    DocumentReviewResponse,
    SelectionRequest,
)

router = APIRouter(tags=["Document reviews"])


def service() -> DocumentReviewService:
    return DocumentReviewService()


def _error(exc: DocumentReviewError) -> HTTPException:
    if isinstance(exc, DocumentReviewNotFoundError):
        return HTTPException(status_code=404, detail={"code": "DOCUMENT_REVIEW_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, DocumentReviewConflictError):
        return HTTPException(status_code=409, detail={"code": "DOCUMENT_REVIEW_CONFLICT", "message": str(exc)})
    return HTTPException(status_code=422, detail={"code": "DOCUMENT_REVIEW_INVALID", "message": str(exc)})


def _project_record(project_id: str, review_id: str, actor: dict[str, Any]) -> dict[str, Any]:
    copilot.v2_service.require_membership(project_id, actor, {"owner", "researcher"})
    try:
        record = service().get(review_id)
    except DocumentReviewError as exc:
        raise _error(exc) from exc
    if record["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail={"code": "DOCUMENT_REVIEW_NOT_FOUND", "message": "Document review not found"}
        )
    return record


@router.post(
    "/projects/{project_id}/document-reviews",
    response_model=DocumentReviewResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_review(
    project_id: str,
    document: Annotated[UploadFile, File(...)],
    actor: copilot.Actor,
) -> dict[str, Any]:
    copilot.v2_service.require_membership(project_id, actor, {"owner", "researcher"})
    filename = Path(document.filename or "document").name
    content = await document.read()
    await document.close()
    try:
        record = await service().create(project_id, filename, content)
    except DocumentReviewError as exc:
        raise _error(exc) from exc
    copilot.v2_repository.audit(
        project_id, actor["actor_id"], "document.review_created", "document_review", record["review_id"]
    )
    return record


@router.get(
    "/projects/{project_id}/document-reviews/{review_id}",
    response_model=DocumentReviewResponse,
    response_model_exclude_none=True,
)
async def get_document_review(project_id: str, review_id: str, actor: copilot.Actor) -> dict[str, Any]:
    return _project_record(project_id, review_id, actor)


@router.put(
    "/projects/{project_id}/document-reviews/{review_id}/content",
    response_model=DocumentReviewResponse,
    response_model_exclude_none=True,
)
async def update_document_content(
    project_id: str, review_id: str, request: DocumentContentUpdateRequest, actor: copilot.Actor
) -> dict[str, Any]:
    _project_record(project_id, review_id, actor)
    try:
        return service().update_content(review_id, request.content)
    except DocumentReviewError as exc:
        raise _error(exc) from exc


@router.post(
    "/projects/{project_id}/document-reviews/{review_id}/reanalyze",
    response_model=DocumentReviewResponse,
    response_model_exclude_none=True,
)
async def reanalyze_document_review(project_id: str, review_id: str, actor: copilot.Actor) -> dict[str, Any]:
    _project_record(project_id, review_id, actor)
    try:
        return await service().reanalyze(review_id)
    except DocumentReviewError as exc:
        raise _error(exc) from exc


@router.post(
    "/projects/{project_id}/document-reviews/{review_id}/verify-claims",
    response_model=DocumentReviewResponse,
    response_model_exclude_none=True,
)
async def verify_document_claims(project_id: str, review_id: str, actor: copilot.Actor) -> dict[str, Any]:
    _project_record(project_id, review_id, actor)
    try:
        record = await service().verify_claim_citations(review_id)
    except DocumentReviewError as exc:
        raise _error(exc) from exc
    copilot.v2_repository.audit(
        project_id,
        actor["actor_id"],
        "document.claims_verified",
        "document_review",
        review_id,
    )
    return record


@router.patch(
    "/projects/{project_id}/document-reviews/{review_id}/annotations/{annotation_id}",
    response_model=DocumentReviewResponse,
    response_model_exclude_none=True,
)
async def decide_annotation(
    project_id: str,
    review_id: str,
    annotation_id: str,
    request: AnnotationActionRequest,
    actor: copilot.Actor,
) -> dict[str, Any]:
    _project_record(project_id, review_id, actor)
    try:
        return service().update_annotation(review_id, annotation_id, request.action)
    except DocumentReviewError as exc:
        raise _error(exc) from exc


@router.post("/projects/{project_id}/document-reviews/{review_id}/explain")
async def explain_selection(
    project_id: str, review_id: str, request: SelectionRequest, actor: copilot.Actor
) -> dict[str, str]:
    _project_record(project_id, review_id, actor)
    try:
        return {
            "explanation": await service().explain(review_id, request.selected_text, request.prefix, request.suffix)
        }
    except DocumentReviewError as exc:
        raise _error(exc) from exc
    except ValueError as exc:
        raise _error(
            DocumentReviewError("AI explanation is unavailable. Check the configured language model.")
        ) from exc


@router.post("/projects/{project_id}/document-reviews/{review_id}/rewrite")
async def rewrite_selection(
    project_id: str, review_id: str, request: SelectionRequest, actor: copilot.Actor
) -> dict[str, str]:
    _project_record(project_id, review_id, actor)
    try:
        return {
            # Never trust an LLM echo for this value: it must exact-match the
            # client selection before a later apply can succeed.
            "old_text": request.selected_text,
            "new_text": await service().rewrite(
                review_id, request.selected_text, request.prefix, request.suffix, request.instruction
            ),
        }
    except DocumentReviewError as exc:
        raise _error(exc) from exc
    except ValueError as exc:
        raise _error(DocumentReviewError("AI rewrite is unavailable. Check the configured language model.")) from exc


@router.post(
    "/projects/{project_id}/document-reviews/{review_id}/apply",
    response_model=DocumentReviewResponse,
    response_model_exclude_none=True,
)
async def apply_rewrite(
    project_id: str, review_id: str, request: ApplyRewriteRequest, actor: copilot.Actor
) -> dict[str, Any]:
    _project_record(project_id, review_id, actor)
    try:
        return service().apply_rewrite(review_id, request.old_text, request.new_text)
    except DocumentReviewError as exc:
        raise _error(exc) from exc
