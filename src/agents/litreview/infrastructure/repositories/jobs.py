from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import get_settings
from src.db.models import (
    EvaluationRecord,
    ReferenceCheck,
    ReportReview,
    ReviewDecision,
    ReviewJob,
    ReviewReport,
    Users,
    V2Message,
    V2ProjectReviewJob,
)
from src.db.session import session_scope
from src.logging_utils import event
from src.services.redis_jobs import RedisJobStatusCache
from src.services.repositories.database import run_migrations

logger = logging.getLogger("litreview.repositories.jobs")

# How long a resume_claimed_at lease lasts before another worker can reclaim
_LEASE_TIMEOUT_SECONDS = 300  # 5 minutes


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _lease_deadline(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _trace_summary(node_name: str, papers_found: int, progress: dict[str, Any]) -> str:
    parts: list[str] = []
    if query := progress.get("search_query"):
        parts.append(f"query='{query}'")
    # A zero here usually means that this node did not modify the paper list,
    # not that the corpus disappeared. Keep the trace focused on meaningful
    # counters and avoid misleading `papers=0` entries in the UI.
    if papers_found > 0:
        parts.append(f"papers={papers_found}")
    if progress.get("valid_claims", 0) > 0:
        parts.append(f"valid_claims={progress['valid_claims']}")
    if progress.get("search_attempt", 0) > 0:
        parts.append(f"search_attempt={progress['search_attempt']}")
    if progress.get("grounding_revision_attempt", 0) > 0:
        parts.append(f"grounding_revisions={progress['grounding_revision_attempt']}")
    if progress.get("review_revision_attempt", 0) > 0:
        parts.append(f"review_revisions={progress['review_revision_attempt']}")
    if last_decision := progress.get("last_decision"):
        parts.append(f"decision={last_decision.get('action')}")
    if warnings := progress.get("warnings"):
        parts.append(f"warnings={len(warnings)}")
    if node_name == "queued":
        return "Job created and waiting for worker"
    return f"{node_name}: " + ", ".join(parts) if parts else ""


class JobRepository:
    """Thread-safe PostgreSQL persistence for jobs, reports, and simulated MVP roles."""

    def __init__(self, database_url: str | None = None, *, initialize: bool = True) -> None:
        settings = get_settings()
        self.settings = settings
        self.database_url = database_url or settings.product_database_url or settings.database_url
        self._write_lock = threading.RLock()
        self._status_cache = RedisJobStatusCache(settings)
        if initialize:
            self.initialize()

    def initialize(self) -> None:
        with self._write_lock:
            run_migrations(self.database_url)

    def _connect(self) -> Any:
        return session_scope(self.database_url)

    def create_job(
        self,
        job_id: str,
        user_id: str,
        role: str,
        topic: str,
        max_results: int,
        execution_mode: str = "review",
        approved_sub_queries: list[str] | None = None,
        response_language: str | None = None,
        workflow_type: str = "litreview",
        request_id: str | None = None,
    ) -> None:
        created_at = _now()
        with self._write_lock, self._connect() as session:
            user = session.get(Users, user_id)
            if user is None:
                session.add(Users(id=user_id, role=role, created_at=created_at))
                session.flush()
            else:
                user.role = role
            session.add(
                ReviewJob(
                    id=job_id,
                    user_id=user_id,
                    topic=topic,
                    max_results=max_results,
                    status="queued",
                    current_node="queued",
                    created_at=created_at,
                    progress_json=json.dumps(
                        {
                            "execution_mode": execution_mode,
                            "response_language": response_language,
                            "workflow_type": workflow_type,
                            "request_id": request_id,
                            "approved_sub_queries": approved_sub_queries or [],
                            "node_trace": [
                                {
                                    "trace_id": f"{job_id}:queued:0",
                                    "node": "queued",
                                    "summary": "Job created and waiting for worker",
                                    "created_at": created_at,
                                    "papers_found": 0,
                                }
                            ],
                        },
                        ensure_ascii=False,
                    ),
                )
            )
        self._status_cache.invalidate(job_id)

    def update_progress(
        self,
        job_id: str,
        current_node: str,
        papers_found: int = 0,
        progress: dict[str, Any] | None = None,
    ) -> None:
        step_summary = _trace_summary(current_node, papers_found, progress or {})
        with self._write_lock, self._connect() as session:
            job = session.get(ReviewJob, job_id)
            if job is None:
                return
            current_progress = json.loads(job.progress_json or "{}")
            current_progress.update(progress or {})
            node_trace = list(current_progress.get("node_trace", []))
            node_trace.append(
                {
                    "trace_id": f"{job_id}:{current_node}:{len(node_trace)}",
                    "node": current_node,
                    "summary": step_summary,
                    "created_at": _now(),
                    "papers_found": papers_found,
                }
            )
            current_progress["node_trace"] = node_trace
            if job.status == "queued":
                job.status = "running"
            job.current_node = current_node
            # The value is the current corpus count; screening may legitimately
            # reduce it to zero, so retaining a historical maximum is wrong.
            job.papers_found = papers_found
            job.progress_json = json.dumps(current_progress, ensure_ascii=False)
        self._status_cache.invalidate(job_id)
        event(
            logger,
            "agent.step",
            state={"job_id": job_id, **(progress or {})},
            node=current_node,
            papers_found=papers_found,
            summary=step_summary,
        )

    def update_status(self, job_id: str, status: str) -> None:
        with self._write_lock, self._connect() as session:
            job = session.get(ReviewJob, job_id)
            if job is not None:
                job.status = status
        self._status_cache.invalidate(job_id)

    def complete_job(self, job_id: str, result: dict[str, Any], *, mark_waiting: bool = True) -> None:
        now = _now()
        with self._write_lock, self._connect() as session:
            job = session.get(ReviewJob, job_id)
            if job is None:
                return
            job.papers_found = result["papers_count"]
            if mark_waiting:
                job.status = "hitl_waiting"
                stage = result.get("hitl_stage")
                job.current_node = f"waiting_for_{stage}" if stage else "hitl_review"
                job.completed_at = now
                job.resume_claimed_at = None
                job.worker_id = None
                job.worker_heartbeat_at = None
                job.lease_expires_at = None
            report = session.get(ReviewReport, job_id)
            payload = json.dumps(result, ensure_ascii=False)
            if report is None:
                session.add(
                    ReviewReport(
                        job_id=job_id,
                        result_json=payload,
                        hitl_approved=0,
                        reviewer_notes="",
                        created_at=now,
                    )
                )
            else:
                report.result_json = payload
                report.hitl_approved = 0
                report.reviewer_notes = ""
                report.created_at = now
        self._status_cache.invalidate(job_id)

    def resume_workflow(self, job_id: str, payload: dict[str, Any]) -> bool:
        """Persist a generic LangGraph interrupt response for the worker."""
        with self._write_lock, self._connect() as session:
            job = session.get(ReviewJob, job_id)
            if job is None or job.status != "hitl_waiting":
                return False
            progress = json.loads(job.progress_json or "{}")
            progress["resume_payload"] = payload
            job.progress_json = json.dumps(progress, ensure_ascii=False)
            job.status = "resuming"
            job.current_node = "resuming"
            job.resume_claimed_at = None
        self._status_cache.invalidate(job_id)
        return True

    def fail_job(self, job_id: str, error: str) -> None:
        with self._write_lock, self._connect() as session:
            job = session.get(ReviewJob, job_id)
            if job is not None:
                job.status = "error"
                job.current_node = "error"
                job.error = error[:1000]
                job.completed_at = _now()
                job.resume_claimed_at = None
                job.worker_id = None
                job.worker_heartbeat_at = None
                job.lease_expires_at = None
        self._status_cache.invalidate(job_id)

    def cancel_job(self, job_id: str, reason: str = "Cancelled by user") -> None:
        """Invalidate the active worker lease before destructive cleanup."""
        with self._write_lock, self._connect() as session:
            job = session.get(ReviewJob, job_id)
            if job is not None:
                job.status = "cancelled"
                job.current_node = "cancelled"
                job.error = reason[:1000]
                job.completed_at = _now()
                job.resume_claimed_at = None
                job.worker_id = None
                job.worker_heartbeat_at = None
                job.lease_expires_at = None
                job.execution_fence += 1
        self._status_cache.invalidate(job_id)

    def fail_orphaned_active_jobs(self, process_started_at: str) -> list[str]:
        """Fail queued/running jobs that belonged to a previous API process.

        FastAPI background tasks are in-memory. After a container restart there
        is no worker left for these rows, so keeping them as ``running`` would
        make the UI poll forever. Reviewer-resume jobs use checkpoint recovery
        separately and are intentionally excluded here.
        """
        completed_at = _now()
        reason = "WORKER_RESTARTED: backend restarted before the research workflow completed"
        with self._write_lock, self._connect() as session:
            rows = session.execute(
                select(ReviewJob.id).where(
                    ReviewJob.status.in_(("queued", "running")),
                    ReviewJob.created_at < process_started_at,
                )
            ).all()
            job_ids = [row[0] for row in rows]
            for job_id in job_ids:
                job = session.get(ReviewJob, job_id)
                if job is not None:
                    job.status = "error"
                    job.current_node = "error"
                    job.error = reason
                    job.completed_at = completed_at
                    job.resume_claimed_at = None
        return job_ids

    def finalize_job(self, job_id: str, final_state: dict) -> None:
        """Update both job status and report JSON with the final graph snapshot.

        Fixes P0.4: prevents status=approved but last_decision=wait_for_human mismatch.
        """
        now = _now()
        final_status = final_state.get("status", "approved")
        decisions = final_state.get("decisions", [])
        with self._write_lock, self._connect() as session:
            job = session.get(ReviewJob, job_id)
            if job is not None:
                job.status = final_status
                job.current_node = "finalize"
                job.completed_at = now
                job.resume_claimed_at = None
                job.worker_id = None
                job.worker_heartbeat_at = None
                job.lease_expires_at = None
            report = session.get(ReviewReport, job_id)
            if report is not None:
                result = json.loads(report.result_json)
                result.update(
                    {
                        "final_status": final_status,
                        "hitl_decision": final_state.get("hitl_decision"),
                        "decision_trace": decisions,
                        "review_revision_attempt": final_state.get("review_revision_attempt", 0),
                        "grounding_revision_attempt": final_state.get("grounding_revision_attempt", 0),
                        "validation_warnings": final_state.get("validation_warnings", []),
                        "finalized_at": now,
                    }
                )
                report.result_json = json.dumps(result, ensure_ascii=False)
        self._status_cache.invalidate(job_id)

    def get_status(self, job_id: str) -> dict[str, Any] | None:
        cached = self._status_cache.get(job_id)
        if cached is not None:
            return cached
        with self._connect() as session:
            job = session.get(ReviewJob, job_id)
            report = session.get(ReviewReport, job_id)
        if job is None:
            return None
        progress = json.loads(job.progress_json or "{}")
        result = json.loads(report.result_json) if report else {}
        claims = result.get("claims", [])
        decisions = result.get("decision_trace", [])
        last_decision = (
            {
                "action": decisions[-1]["action"],
                "reason": decisions[-1]["reason"],
            }
            if decisions
            else progress.get("last_decision")
        )
        warnings = (
            [*result.get("source_warnings", []), *result.get("validation_warnings", [])]
            if report
            else progress.get("warnings", [])
        )
        snapshot = {
            "job_id": job.id,
            "status": job.status,
            "current_node": job.current_node,
            "papers_found": job.papers_found,
            "error": job.error,
            "valid_claims": (
                len([claim for claim in claims if claim.get("validation_status") == "valid"])
                if report
                else progress.get("valid_claims", 0)
            ),
            "search_attempt": result.get("search_attempt", progress.get("search_attempt", 0)),
            "grounding_revision_attempt": result.get(
                "grounding_revision_attempt", progress.get("grounding_revision_attempt", 0)
            ),
            "review_revision_attempt": result.get(
                "review_revision_attempt", progress.get("review_revision_attempt", 0)
            ),
            "search_query": result.get("search_query", progress.get("search_query")),
            "query_history": result.get("query_history", progress.get("query_history", [])),
            "sub_queries": result.get("sub_queries", progress.get("sub_queries", [])),
            "selected_paper_ids": result.get("selected_paper_ids", progress.get("selected_paper_ids", [])),
            "embedding_backend": result.get("embedding_backend", progress.get("embedding_backend")),
            "embedding_collection": result.get("embedding_collection", progress.get("embedding_collection")),
            "hitl_stage": result.get("hitl_stage", progress.get("hitl_stage")),
            "execution_mode": result.get("execution_mode", progress.get("execution_mode", "review")),
            "last_decision": last_decision,
            "warnings": warnings,
            "node_trace": progress.get("node_trace", []),
            "papers": result.get("papers", progress.get("papers", [])) if report else progress.get("papers", []),
        }
        self._status_cache.set(job_id, snapshot)
        return snapshot

    def delete_job(self, job_id: str) -> bool:
        """Delete a review job and every V1 record owned by it."""
        with self._write_lock, self._connect() as session:
            job = session.get(ReviewJob, job_id)
            if job is None:
                return False
            for model in (EvaluationRecord, ReviewDecision, ReferenceCheck, ReportReview, ReviewReport):
                session.execute(delete(model).where(model.job_id == job_id))
            session.delete(job)
        self._status_cache.invalidate(job_id)
        return True

    def delete_checkpoint_data(self, thread_id: str) -> None:
        """Remove all LangGraph PostgreSQL checkpoint rows for a job thread."""
        with self._write_lock, self._connect() as session:
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                session.execute(text(f"DELETE FROM {table} WHERE thread_id = :thread_id"), {"thread_id": thread_id})

    def get_result(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as session:
            job = session.get(ReviewJob, job_id)
            report = session.get(ReviewReport, job_id)
            review_row = session.get(ReportReview, job_id)
            decisions: list[dict[str, Any]] = []
            reference_checks: list[dict[str, Any]] = []
            if review_row:
                decisions = [
                    dict(item)
                    for item in session.execute(
                        select(
                            ReviewDecision.claim_id,
                            ReviewDecision.verdict,
                            ReviewDecision.note,
                        )
                        .where(ReviewDecision.job_id == job_id, ReviewDecision.reviewer_id == review_row.reviewer_id)
                        .order_by(ReviewDecision.claim_id)
                    )
                    .mappings()
                    .all()
                ]
                reference_checks = [
                    dict(item)
                    for item in session.execute(
                        select(
                            ReferenceCheck.paper_id,
                            ReferenceCheck.verdict,
                            ReferenceCheck.note,
                        )
                        .where(
                            ReferenceCheck.job_id == job_id,
                            ReferenceCheck.reviewer_id == review_row.reviewer_id,
                        )
                        .order_by(ReferenceCheck.paper_id)
                    )
                    .mappings()
                    .all()
                ]
        if job is None or report is None:
            return None
        result = json.loads(report.result_json)
        result.setdefault("original_topic", job.topic)
        result.setdefault("search_query", "")
        result.setdefault("query_history", [])
        result.setdefault("source_warnings", [])
        result.setdefault("revision_log", [])
        result.update(
            {
                "job_id": job.id,
                "status": job.status,
                "topic": job.topic,
                "papers_count": job.papers_found,
                "review_summary": self.get_review_summary(job_id, result),
                "review": (
                    {
                        "reviewer_id": review_row.reviewer_id,
                        "report_decision": review_row.decision,
                        "report_note": review_row.note,
                        "reviewed_at": review_row.reviewed_at,
                        "decisions": decisions,
                        "reference_checks": reference_checks,
                    }
                    if review_row
                    else None
                ),
            }
        )
        return result

    def get_review_summary(
        self,
        job_id: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        if result is None:
            with self._connect() as session:
                report = session.get(ReviewReport, job_id)
            result = json.loads(report.result_json) if report else {}
        with self._connect() as session:
            rr = session.get(ReportReview, job_id)
            reviewer_id = rr.reviewer_id if rr else None
            if reviewer_id:
                rows = session.execute(
                    select(ReviewDecision.verdict, func.count().label("total"))
                    .where(ReviewDecision.job_id == job_id, ReviewDecision.reviewer_id == reviewer_id)
                    .group_by(ReviewDecision.verdict)
                ).all()
            else:
                # No review submitted yet: use latest-per-claim deduplication
                ranked = (
                    select(
                        ReviewDecision.claim_id.label("claim_id"),
                        ReviewDecision.verdict.label("verdict"),
                        func.row_number()
                        .over(
                            partition_by=ReviewDecision.claim_id,
                            order_by=ReviewDecision.reviewed_at.desc(),
                        )
                        .label("rn"),
                    )
                    .where(ReviewDecision.job_id == job_id)
                    .subquery()
                )
                rows = session.execute(
                    select(ranked.c.verdict, func.count().label("total"))
                    .where(ranked.c.rn == 1)
                    .group_by(ranked.c.verdict)
                ).all()
        counts = {row.verdict: int(row.total) for row in rows}
        supported = counts.get("supported", 0)
        unsupported = counts.get("unsupported", 0)
        return {
            "total_claims": len(result.get("claims", [])),
            "reviewed_claims": supported + unsupported,
            "supported_claims": supported,
            "unsupported_claims": unsupported,
        }

    def save_review(
        self,
        job_id: str,
        reviewer_id: str,
        decisions: list[dict[str, Any]],
        reference_checks: list[dict[str, Any]],
        report_decision: str,
        report_note: str,
        *,
        resume_workflow: bool = True,
    ) -> dict[str, Any] | None:
        with self._write_lock, self._connect() as session:
            exists = session.get(ReviewReport, job_id)
            if not exists:
                return None
            now = _now()
            user = session.get(Users, reviewer_id)
            if user is None:
                session.add(Users(id=reviewer_id, role="reviewer", created_at=now))
            else:
                user.role = "reviewer"
            # The review report stores ``reviewed_by`` as a foreign key.  This
            # session disables autoflush, so persist the reviewer before the
            # PostgreSQL upserts below reference that user.
            session.flush()

            session.execute(
                delete(ReviewDecision).where(ReviewDecision.job_id == job_id, ReviewDecision.reviewer_id == reviewer_id)
            )
            session.execute(
                delete(ReferenceCheck).where(ReferenceCheck.job_id == job_id, ReferenceCheck.reviewer_id == reviewer_id)
            )

            for decision in decisions:
                stmt = pg_insert(ReviewDecision).values(
                    job_id=job_id,
                    reviewer_id=reviewer_id,
                    claim_id=decision["claim_id"],
                    verdict=decision["verdict"],
                    note=decision.get("note", ""),
                    reviewed_at=now,
                )
                session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[ReviewDecision.job_id, ReviewDecision.reviewer_id, ReviewDecision.claim_id],
                        set_={
                            "verdict": decision["verdict"],
                            "note": decision.get("note", ""),
                            "reviewed_at": now,
                        },
                    )
                )
            for check in reference_checks:
                stmt = pg_insert(ReferenceCheck).values(
                    job_id=job_id,
                    reviewer_id=reviewer_id,
                    paper_id=check["paper_id"],
                    verdict=check["verdict"],
                    note=check.get("note", ""),
                    checked_at=now,
                )
                session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[ReferenceCheck.job_id, ReferenceCheck.reviewer_id, ReferenceCheck.paper_id],
                        set_={
                            "verdict": check["verdict"],
                            "note": check.get("note", ""),
                            "checked_at": now,
                        },
                    )
                )
            report_review = session.get(ReportReview, job_id)
            if report_review is None:
                stmt = pg_insert(ReportReview).values(
                    job_id=job_id,
                    reviewer_id=reviewer_id,
                    decision=report_decision,
                    note=report_note,
                    reviewed_at=now,
                )
                session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[ReportReview.job_id],
                        set_={
                            "reviewer_id": reviewer_id,
                            "decision": report_decision,
                            "note": report_note,
                            "reviewed_at": now,
                        },
                    )
                )
            else:
                report_review.reviewer_id = reviewer_id
                report_review.decision = report_decision
                report_review.note = report_note
                report_review.reviewed_at = now
            job = session.get(ReviewJob, job_id)
            if job is not None and resume_workflow:
                job.status = "resuming"
            report = session.get(ReviewReport, job_id)
            if report is not None:
                report.hitl_approved = int(report_decision == "approve")
                report.reviewer_notes = report_note
                report.reviewed_by = reviewer_id
                report.reviewed_at = now
            decision_rows = session.execute(
                select(ReviewDecision.verdict, func.count().label("total"))
                .where(ReviewDecision.job_id == job_id, ReviewDecision.reviewer_id == reviewer_id)
                .group_by(ReviewDecision.verdict)
            )
            reference_rows = session.execute(
                select(ReferenceCheck.verdict, func.count().label("total"))
                .where(ReferenceCheck.job_id == job_id, ReferenceCheck.reviewer_id == reviewer_id)
                .group_by(ReferenceCheck.verdict)
            )
        decision_counts = {row.verdict: int(row.total) for row in decision_rows}
        reference_counts = {row.verdict: int(row.total) for row in reference_rows}
        supported = decision_counts.get("supported", 0)
        unsupported = decision_counts.get("unsupported", 0)
        valid_references = reference_counts.get("valid", 0)
        invalid_references = reference_counts.get("invalid", 0)
        reviewed_claims = supported + unsupported
        checked_references = valid_references + invalid_references
        self._status_cache.invalidate(job_id)
        return {
            "job_id": job_id,
            "status": "resuming" if resume_workflow else "approved",
            "reviewed_claims": reviewed_claims,
            "supported_claims": supported,
            "unsupported_claims": unsupported,
            "claim_support_accuracy": (supported / reviewed_claims if reviewed_claims else None),
            "checked_references": checked_references,
            "valid_references": valid_references,
            "invalid_references": invalid_references,
            "reference_validity": (valid_references / checked_references if checked_references else None),
        }

    def list_jobs(self, limit: int = 50, status_filter: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as session:
            query = (
                select(
                    ReviewJob.id.label("job_id"),
                    ReviewJob.topic,
                    ReviewJob.user_id,
                    ReviewJob.status,
                    ReviewJob.papers_found,
                    ReviewJob.created_at,
                )
                .order_by(ReviewJob.created_at.desc())
                .limit(limit)
            )
            if status_filter:
                query = query.where(ReviewJob.status == status_filter)
            rows = session.execute(query).mappings().all()
        return [dict(row) for row in rows]

    def save_evaluation(
        self,
        job_id: str,
        evaluator_id: str,
        manual_minutes: float,
        mvp_minutes: float,
        usefulness_score: float,
        notes: str,
    ) -> dict | None:
        evaluated_at = _now()
        with self._write_lock, self._connect() as session:
            # Only allow evaluations for approved jobs with a completed review
            job = session.get(ReviewJob, job_id)
            if not job or job.status != "approved":
                return None
            review = session.get(ReviewReport, job_id)
            if not review or review.hitl_approved != 1:
                return None
            existing = session.get(EvaluationRecord, job_id)
            if existing is None:
                session.add(
                    EvaluationRecord(
                        job_id=job_id,
                        evaluator_id=evaluator_id,
                        manual_minutes=manual_minutes,
                        mvp_minutes=mvp_minutes,
                        usefulness_score=usefulness_score,
                        notes=notes,
                        evaluated_at=evaluated_at,
                    )
                )
            else:
                existing.evaluator_id = evaluator_id
                existing.manual_minutes = manual_minutes
                existing.mvp_minutes = mvp_minutes
                existing.usefulness_score = usefulness_score
                existing.notes = notes
                existing.evaluated_at = evaluated_at
        return self.get_evaluation(job_id)

    def get_evaluation(self, job_id: str) -> dict | None:
        with self._connect() as session:
            row = session.get(EvaluationRecord, job_id)
            if not row:
                return None
            return {
                "job_id": row.job_id,
                "evaluator_id": row.evaluator_id,
                "manual_minutes": row.manual_minutes,
                "mvp_minutes": row.mvp_minutes,
                "usefulness_score": row.usefulness_score,
                "notes": row.notes,
                "evaluated_at": row.evaluated_at,
            }

    def get_mvp_metrics(self) -> dict:
        with self._connect() as session:
            eval_counts = session.execute(
                select(func.count())
                .select_from(EvaluationRecord)
                .join(ReviewJob, ReviewJob.id == EvaluationRecord.job_id)
                .where(ReviewJob.status == "approved")
            ).scalar_one()

            decision_rows = session.execute(
                select(
                    ReviewDecision.job_id,
                    ReviewDecision.claim_id,
                    ReviewDecision.verdict,
                    ReviewDecision.reviewed_at,
                )
                .join(
                    ReportReview,
                    (ReportReview.job_id == ReviewDecision.job_id)
                    & (ReportReview.reviewer_id == ReviewDecision.reviewer_id),
                )
                .join(ReviewJob, ReviewJob.id == ReviewDecision.job_id)
                .where(ReviewJob.status == "approved")
            ).all()
            latest_decisions: dict[tuple[str, str], tuple[str, str]] = {}
            for row in decision_rows:
                key = (row.job_id, row.claim_id)
                previous = latest_decisions.get(key)
                if previous is None or row.reviewed_at > previous[1]:
                    latest_decisions[key] = (row.verdict, row.reviewed_at)
            reviewed_claims = len(latest_decisions)
            supported_claims = sum(1 for verdict, _ in latest_decisions.values() if verdict == "supported")
            claim_acc = supported_claims / reviewed_claims if reviewed_claims else 0.0

            report_rows = (
                session.execute(
                    select(ReviewReport.result_json)
                    .join(ReviewJob, ReviewJob.id == ReviewReport.job_id)
                    .where(ReviewJob.status == "approved")
                )
                .scalars()
                .all()
            )
            total_claims = sum(len(json.loads(result_json).get("claims", [])) for result_json in report_rows)
            review_coverage = min(1.0, reviewed_claims / total_claims if total_claims else 0.0)

            reference_rows = session.execute(
                select(
                    ReferenceCheck.job_id,
                    ReferenceCheck.paper_id,
                    ReferenceCheck.verdict,
                    ReferenceCheck.checked_at,
                )
                .join(
                    ReportReview,
                    (ReportReview.job_id == ReferenceCheck.job_id)
                    & (ReportReview.reviewer_id == ReferenceCheck.reviewer_id),
                )
                .join(ReviewJob, ReviewJob.id == ReferenceCheck.job_id)
                .where(ReviewJob.status == "approved")
            ).all()
            latest_refs: dict[tuple[str, str], tuple[str, str]] = {}
            for row in reference_rows:
                key = (row.job_id, row.paper_id)
                previous = latest_refs.get(key)
                if previous is None or row.checked_at > previous[1]:
                    latest_refs[key] = (row.verdict, row.checked_at)
            checked_refs = len(latest_refs)
            valid_refs = sum(1 for verdict, _ in latest_refs.values() if verdict == "valid")
            ref_val = valid_refs / checked_refs if checked_refs else 0.0

            total_refs = sum(len(json.loads(result_json).get("references", [])) for result_json in report_rows)
            reference_coverage = min(1.0, checked_refs / total_refs if total_refs else 0.0)

            rows = session.execute(
                select(EvaluationRecord.manual_minutes, EvaluationRecord.mvp_minutes)
                .join(ReviewJob, ReviewJob.id == EvaluationRecord.job_id)
                .where(ReviewJob.status == "approved")
            ).all()
            reductions = [
                (row.manual_minutes - row.mvp_minutes) / row.manual_minutes for row in rows if row.manual_minutes > 0
            ]
            reductions.sort()
            if reductions:
                mid = len(reductions) // 2
                med_reduction = (
                    reductions[mid] if len(reductions) % 2 == 1 else (reductions[mid - 1] + reductions[mid]) / 2.0
                )
            else:
                med_reduction = 0.0

            mvp_passed = (
                reviewed_claims >= 30
                and eval_counts >= 5
                and ref_val >= 1.0
                and claim_acc >= 0.8
                and med_reduction >= 0.5
                and review_coverage >= 1.0
                and reference_coverage >= 1.0
            )
            return {
                "reports_evaluated": eval_counts,
                "claims_reviewed": reviewed_claims,
                "supported_claims": supported_claims,
                "claim_support_accuracy": claim_acc,
                "claim_review_coverage": review_coverage,
                "references_checked": checked_refs,
                "valid_references": valid_refs,
                "reference_validity": ref_val,
                "reference_review_coverage": reference_coverage,
                "median_time_reduction": med_reduction,
                "mvp_passed": bool(mvp_passed),
            }

    def claim_queued_jobs(
        self, limit: int | None = None, *, worker_id: str | None = None, lease_seconds: int | None = None
    ) -> list[tuple[str, dict[str, Any]]]:
        """Atomically claim queued jobs, allowing at most two per project."""
        lease_cutoff = (datetime.now(UTC) - timedelta(seconds=_LEASE_TIMEOUT_SECONDS)).isoformat()
        now = _now()
        lease_expires_at = _lease_deadline(lease_seconds or self.settings.worker_lease_seconds)
        with self._write_lock, self._connect() as session:
            statement = (
                select(ReviewJob)
                .where(
                    ReviewJob.status == "queued",
                    or_(ReviewJob.resume_claimed_at.is_(None), ReviewJob.resume_claimed_at < lease_cutoff),
                )
                .order_by(ReviewJob.created_at, ReviewJob.id)
                .with_for_update(skip_locked=True)
            )
            if limit is not None:
                statement = statement.limit(limit)
            rows = session.execute(statement).scalars().all()
            project_by_job = dict(
                session.execute(
                    select(V2ProjectReviewJob.job_id, V2ProjectReviewJob.project_id).where(
                        V2ProjectReviewJob.job_id.in_([job.id for job in rows])
                    )
                ).all()
            )
            conversation_by_job = dict(
                session.execute(
                    select(V2ProjectReviewJob.job_id, V2ProjectReviewJob.conversation_id).where(
                        V2ProjectReviewJob.job_id.in_([job.id for job in rows])
                    )
                ).all()
            )
            messages_by_conversation: dict[str, list[dict[str, str]]] = {}
            conversation_ids = {value for value in conversation_by_job.values() if value}
            if conversation_ids:
                message_rows = session.execute(
                    select(V2Message.conversation_id, V2Message.role, V2Message.text)
                    .where(V2Message.conversation_id.in_(conversation_ids))
                    .order_by(V2Message.created_at, V2Message.message_id)
                ).all()
                for conversation_id, role, text_value in message_rows:
                    messages_by_conversation.setdefault(conversation_id, []).append({"role": role, "text": text_value})
            active_counts: dict[str, int] = {}
            if project_by_job:
                active_rows = session.execute(
                    select(V2ProjectReviewJob.project_id, func.count(ReviewJob.id))
                    .join(ReviewJob, ReviewJob.id == V2ProjectReviewJob.job_id)
                    .where(
                        V2ProjectReviewJob.project_id.in_(set(project_by_job.values())),
                        ReviewJob.status.in_(("running", "resuming")),
                    )
                    .group_by(V2ProjectReviewJob.project_id)
                ).all()
                active_counts = {project_id: int(count) for project_id, count in active_rows}
            jobs = []
            for job in rows:
                project_id = project_by_job.get(job.id)
                if project_id is not None and active_counts.get(project_id, 0) >= 2:
                    continue
                job.resume_claimed_at = now
                job.status = "running"
                job.worker_id = worker_id
                job.worker_heartbeat_at = now
                job.lease_expires_at = lease_expires_at
                job.execution_fence += 1
                if project_id is not None:
                    active_counts[project_id] = active_counts.get(project_id, 0) + 1
                progress = json.loads(job.progress_json or "{}")
                approved_sub_queries = list(progress.get("approved_sub_queries") or [])
                jobs.append(
                    (
                        job.id,
                        {
                            "original_topic": job.topic,
                            "thread_id": job.id,
                            "run_id": job.id,
                            "session_id": job.id,
                            "conversation_id": conversation_by_job.get(job.id),
                            "max_results": job.max_results,
                            "user_id": job.user_id,
                            "execution_mode": progress.get("execution_mode", "review"),
                            "response_language": progress.get("response_language"),
                            "workflow_type": progress.get("workflow_type", "litreview"),
                            "request_id": progress.get("request_id"),
                            "sub_queries": approved_sub_queries,
                            "skip_subquery_review": bool(approved_sub_queries),
                            "conversation_history": messages_by_conversation.get(conversation_by_job.get(job.id), []),
                            "job_id": job.id,
                            "current_node": "queued",
                            "source_warnings": [],
                            "error": None,
                            "_worker_id": worker_id,
                            "_execution_fence": job.execution_fence,
                        },
                    )
                )
        for claimed_job_id, _ in jobs:
            self._status_cache.invalidate(claimed_job_id)
        return jobs

    def get_resuming_jobs(
        self, limit: int | None = None, *, worker_id: str | None = None, lease_seconds: int | None = None
    ) -> list[tuple[str, dict[str, Any]]]:
        """Atomically claim resuming jobs using a lease timeout mechanism.

        A job is eligible for recovery if:
          - status = 'resuming'
          - resume_claimed_at is NULL (never claimed) OR older than _LEASE_TIMEOUT_SECONDS
        This prevents jobs from being permanently stuck if a process crashes mid-claim.
        """
        lease_cutoff = (datetime.now(UTC) - timedelta(seconds=_LEASE_TIMEOUT_SECONDS)).isoformat()
        now = _now()
        lease_expires_at = _lease_deadline(lease_seconds or self.settings.worker_lease_seconds)

        with self._write_lock, self._connect() as session:
            statement = (
                select(ReviewJob)
                .where(
                    ReviewJob.status == "resuming",
                    or_(ReviewJob.resume_claimed_at.is_(None), ReviewJob.resume_claimed_at < lease_cutoff),
                )
                .order_by(ReviewJob.created_at, ReviewJob.id)
                .with_for_update(skip_locked=True)
            )
            if limit is not None:
                statement = statement.limit(limit)
            rows = session.execute(statement).scalars().all()
            for job in rows:
                job.resume_claimed_at = now
                job.worker_id = worker_id
                job.worker_heartbeat_at = now
                job.lease_expires_at = lease_expires_at
                job.execution_fence += 1
            jobs = []
            for job in rows:
                job_id = job.id
                report = session.get(ReportReview, job_id)
                progress = json.loads(job.progress_json or "{}")
                if not report:
                    payload = progress.get("resume_payload")
                    if not isinstance(payload, dict):
                        continue
                    payload["_execution_fence"] = job.execution_fence
                    payload.setdefault("run_id", job.id)
                    payload.setdefault("request_id", progress.get("request_id"))
                    jobs.append((job_id, payload))
                    continue
                reviewer_id = report.reviewer_id
                decisions = (
                    session.execute(
                        select(ReviewDecision.claim_id, ReviewDecision.verdict, ReviewDecision.note).where(
                            ReviewDecision.job_id == job_id,
                            ReviewDecision.reviewer_id == reviewer_id,
                        )
                    )
                    .mappings()
                    .all()
                )
                refs = (
                    session.execute(
                        select(ReferenceCheck.paper_id, ReferenceCheck.verdict, ReferenceCheck.note).where(
                            ReferenceCheck.job_id == job_id,
                            ReferenceCheck.reviewer_id == reviewer_id,
                        )
                    )
                    .mappings()
                    .all()
                )
                payload = {
                    "hitl_decision": report.decision,
                    "review_feedback": report.note,
                    "review_decisions": [dict(d) for d in decisions],
                    "reference_checks": [dict(r) for r in refs],
                    "_worker_id": worker_id,
                    "_execution_fence": job.execution_fence,
                }
                jobs.append((job_id, payload))
            return jobs

    def renew_worker_leases(self, worker_id: str, lease_seconds: int | None = None) -> int:
        """Heartbeat all active jobs owned by this worker; never renew another owner's lease."""
        now = _now()
        expires_at = _lease_deadline(lease_seconds or self.settings.worker_lease_seconds)
        with self._write_lock, self._connect() as session:
            jobs = (
                session.execute(
                    select(ReviewJob).where(
                        ReviewJob.worker_id == worker_id,
                        ReviewJob.status.in_(("running", "resuming")),
                    )
                )
                .scalars()
                .all()
            )
            for job in jobs:
                job.worker_heartbeat_at = now
                job.lease_expires_at = expires_at
            return len(jobs)

    def reclaim_expired_jobs(self) -> list[str]:
        """Return work from a dead worker to the durable queue with a new fence later."""
        now = _now()
        with self._write_lock, self._connect() as session:
            jobs = (
                session.execute(
                    select(ReviewJob)
                    .where(
                        ReviewJob.status.in_(("running", "resuming")),
                        ReviewJob.lease_expires_at.is_not(None),
                        ReviewJob.lease_expires_at < now,
                    )
                    .with_for_update(skip_locked=True)
                )
                .scalars()
                .all()
            )
            job_ids = []
            for job in jobs:
                job.status = "resuming" if job.status == "resuming" else "queued"
                job.current_node = "worker_recovery"
                job.resume_claimed_at = None
                job.worker_id = None
                job.worker_heartbeat_at = None
                job.lease_expires_at = None
                job_ids.append(job.id)
        for job_id in job_ids:
            self._status_cache.invalidate(job_id)
        return job_ids

    def assert_execution_fence(self, job_id: str, worker_id: str, execution_fence: int) -> None:
        """Reject writes from a worker that no longer owns this execution lease."""
        now = _now()
        with self._connect() as session:
            job = session.get(ReviewJob, job_id)
            owned = bool(
                job
                and job.worker_id == worker_id
                and job.execution_fence == execution_fence
                and job.lease_expires_at
                and job.lease_expires_at >= now
            )
        if not owned:
            raise RuntimeError(f"WORKER_FENCE_LOST: job={job_id} worker={worker_id}")
