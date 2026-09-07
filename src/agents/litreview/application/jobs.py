from __future__ import annotations

import logging
import re
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from src.agents.litreview.infrastructure.repositories.copilot import V2Repository
from src.agents.litreview.infrastructure.repositories.jobs import JobRepository
from src.agents.litreview.workflow.graph import uncompiled_graph
from src.agents.research_gap.application.service import ResearchGapJobService
from src.config import get_settings
from src.logging_utils import event
from src.services.langfuse_observability import langfuse_graph_config
from src.services.language import response_language

logger = logging.getLogger(__name__)

_PAPER_MARKER = re.compile(r"\[\[([A-Za-z0-9_.:-]+)\]\]")


def _citation_token(
    paper_id: str, reference_numbers: dict[str, int], references_by_id: dict[str, dict[str, Any]]
) -> str:
    """Return a compact, safe-to-render numbered citation token for chat."""
    number = reference_numbers.get(paper_id)
    url = references_by_id.get(paper_id, {}).get("url")
    if number and isinstance(url, str) and url.startswith("https://"):
        return f"[[cite:{number}:{url}]]"
    return f"[{number}]" if number else ""


def _render_numbered_citations(
    text: str, reference_numbers: dict[str, int], references_by_id: dict[str, dict[str, Any]]
) -> str:
    return _PAPER_MARKER.sub(
        lambda match: _citation_token(match.group(1), reference_numbers, references_by_id) or match.group(0),
        text,
    )


def _progress_payload(values: dict[str, Any]) -> dict[str, Any]:
    """Keep a small, API-safe progress snapshot for status polling."""

    progress: dict[str, Any] = {}
    if "claims" in values:
        progress["valid_claims"] = len(
            [claim for claim in values.get("claims", []) if claim.get("validation_status") == "valid"]
        )
    for key in (
        "search_attempt",
        "grounding_revision_attempt",
        "review_revision_attempt",
        "search_query",
        "query_history",
        "sub_queries",
        "selected_paper_ids",
        "hitl_stage",
        "embedding_backend",
        "embedding_collection",
    ):
        if key in values:
            progress[key] = values[key]

    # Persist a compact, user-facing snapshot as soon as the search node
    # returns. This is intentionally limited: status polling should reveal
    # which papers the agent is evaluating without serializing full abstracts.
    if "papers" in values:
        progress["papers"] = [
            {
                "paper_id": paper.get("paper_id", ""),
                "title": paper.get("title", "Untitled paper"),
                "authors": paper.get("authors", []),
                "year": paper.get("year"),
                "url": paper.get("url", ""),
                "cited_by_count": paper.get("cited_by_count", 0),
                "relevance_score": paper.get("relevance_score"),
                "source": paper.get("source", "unknown"),
                "ingestion": paper.get("ingestion"),
            }
            for paper in (values.get("papers") or [])[:12]
            if isinstance(paper, dict)
        ]

    validation_warnings = values.get("validation_warnings")
    source_warnings = values.get("source_warnings")
    if validation_warnings is not None or source_warnings is not None:
        progress["warnings"] = [*(source_warnings or []), *(validation_warnings or [])]
    decisions = values.get("decisions")
    if decisions:
        progress["last_decision"] = {
            "action": decisions[-1]["action"],
            "reason": decisions[-1]["reason"],
        }
    return progress


def _result_from_state(state: dict[str, Any], paused_nodes: list[str] | None = None) -> dict[str, Any]:
    """Create the single persisted report contract used by run and resume."""

    paused_nodes = paused_nodes or []
    hitl_stage = state.get("hitl_stage")
    if "human_review" in paused_nodes:
        hitl_stage = "review"
    return {
        "execution_mode": state.get("execution_mode", "review"),
        "response_language": state.get("response_language"),
        "session_id": state.get("session_id") or state.get("job_id", ""),
        "conversation_id": state.get("conversation_id"),
        "original_topic": state.get("original_topic", ""),
        "intent": state.get("intent", "litreview"),
        "intent_reason": state.get("intent_reason", ""),
        "assistant_response": state.get("assistant_response", ""),
        "search_query": state.get("search_query", ""),
        "query_history": state.get("query_history", []),
        "sub_queries": state.get("sub_queries", []),
        "selected_paper_ids": state.get("selected_paper_ids", []),
        "embedding_backend": state.get("embedding_backend"),
        "embedding_collection": state.get("embedding_collection"),
        "hitl_stage": hitl_stage,
        "papers": state.get("papers", []),
        "claims": state.get("claims", []),
        "evidence_rows": state.get("evidence_rows", []),
        "themes": state.get("themes", []),
        "potential_gaps": state.get("potential_gaps", []),
        "references": state.get("references", []),
        "scope_disclaimer": state.get("scope_disclaimer", ""),
        "literature_review": state.get("literature_review"),
        "decision_trace": state.get("decisions", []),
        "source_warnings": state.get("source_warnings", []),
        "validation_warnings": state.get("validation_warnings", []),
        "papers_count": len(state.get("papers", [])),
        "search_attempt": state.get("search_attempt", 0),
        "grounding_revision_attempt": state.get("grounding_revision_attempt", 0),
        "review_revision_attempt": state.get("review_revision_attempt", 0),
        "revision_log": state.get("revision_log", []),
    }


def _render_report_message(result: dict[str, Any]) -> str:
    """Render the final literature-review article and its numbered references."""
    valid_claims = [claim for claim in result.get("claims", []) if claim.get("validation_status") == "valid"]
    themes = result.get("themes") or []
    references = result.get("references") or []
    references_by_id = {reference.get("paper_id"): reference for reference in references}
    reference_numbers = {reference.get("paper_id"): index for index, reference in enumerate(references, start=1)}
    topic = result.get("original_topic") or result.get("topic", "")
    vietnamese = (
        result.get("response_language") == "Vietnamese"
        if result.get("response_language")
        else response_language(topic) == "Vietnamese"
    )
    review = result.get("literature_review") or {}
    lines: list[str] = []
    article_in_english = isinstance(review, dict) and bool(review.get("introduction") and review.get("sections"))
    article_labels = (
        {
            "introduction": "Giới thiệu",
            "conclusion": "Kết luận",
            "limitations": "Phạm vi và hạn chế",
            "references": "Tài liệu tham khảo",
        }
        if vietnamese
        else {
            "introduction": "Introduction",
            "conclusion": "Conclusion",
            "limitations": "Limitations",
            "references": "References",
        }
    )

    def article_text(value: Any) -> str:
        return _render_numbered_citations(str(value or "").strip(), reference_numbers, references_by_id)

    if article_in_english:
        lines.extend([f"## {article_labels['introduction']}", article_text(review["introduction"]), ""])
        for section in review["sections"]:
            title = str(section.get("title") or ("Chủ đề" if vietnamese else "Theme"))
            paragraphs = [
                article_text(paragraph) for paragraph in section.get("paragraphs", []) if str(paragraph).strip()
            ]
            if paragraphs:
                lines.extend([f"## {title}", *paragraphs, ""])
        if review.get("conclusion"):
            lines.extend([f"## {article_labels['conclusion']}", article_text(review["conclusion"]), ""])
        if review.get("limitations"):
            lines.extend([f"## {article_labels['limitations']}", article_text(review["limitations"]), ""])
    else:
        claims_by_id = {claim.get("claim_id"): claim for claim in valid_claims}
        for theme in themes:
            claim = claims_by_id.get(theme.get("summary_claim_id"), {})
            paper_ids = claim.get("supporting_paper_ids", [])
            citations = " ".join(
                _citation_token(paper_id, reference_numbers, references_by_id)
                for paper_id in paper_ids
                if _citation_token(paper_id, reference_numbers, references_by_id)
            )
            if claim.get("text"):
                lines.extend(
                    [
                        f"## {theme.get('title', 'Chủ đề')}",
                        f"{claim['text']}{(' ' + citations) if citations else ''}",
                        "",
                    ]
                )
        if not lines:
            lines.extend(
                [
                    "## Tổng hợp" if vietnamese else "## Synthesis",
                    *(claim.get("text", "") for claim in valid_claims[:5]),
                    "",
                ]
            )

    if references:
        lines.append(
            f"## {article_labels['references']}"
            if article_in_english
            else ("## Tài liệu tham khảo" if vietnamese else "## References")
        )
        for reference in references:
            paper_id = reference.get("paper_id", "")
            authors = ", ".join(reference.get("authors", [])[:3]) or (
                "Không rõ tác giả" if vietnamese else "Unknown author"
            )
            year = reference.get("year") or ("không rõ năm" if vietnamese else "n.d.")
            marker = _citation_token(paper_id, reference_numbers, references_by_id)
            title = reference.get("title") or ("Chưa có tiêu đề" if vietnamese else "Untitled paper")
            lines.append(f"- {marker} {authors} ({year}). {title}")
        lines.append("")
    return "\n".join(lines)


def _persist_report_message(result: dict[str, Any], job_id: str) -> None:
    """Make the complete, finalized research answer visible in its conversation."""
    link = V2Repository().project_for_job(job_id)
    conversation_id = result.get("conversation_id") or (link.get("conversation_id") if link else None)
    if not conversation_id:
        return
    if result.get("intent") == "out_of_scope":
        V2Repository().create_assistant_message(
            conversation_id,
            result.get("assistant_response") or "I can only help with academic literature reviews.",
            message_type="assistant",
            client_message_id=f"intent_guardrail:{job_id}",
        )
        return
    V2Repository().create_assistant_message(
        conversation_id,
        _render_report_message(result),
        message_type="research_report",
        client_message_id=f"research_report:{job_id}",
    )


def _graph_config(job_id: str, operation: str) -> dict[str, Any]:
    """Build the single runnable config for an entire graph execution."""
    config: dict[str, Any] = {"configurable": {"thread_id": job_id}}
    if observability_config := langfuse_graph_config(job_id=job_id, operation=operation):
        config.update(observability_config)
    return config


def _paper_progress_counts(values: dict[str, Any], previous_total: int) -> tuple[int, int]:
    """Return the current node count and the latest corpus count.

    A missing ``papers`` key means the node did not update the corpus, while an
    explicit empty list means the node filtered the corpus down to zero.
    """
    if "papers" not in values:
        return previous_total, previous_total
    current_total = len(values.get("papers") or [])
    return current_total, current_total


class LitReviewJobService:
    def __init__(self, repository: JobRepository | None = None) -> None:
        self.repository = repository or JobRepository()

    def _assert_fence(self, job_id: str, worker_id: str | None, execution_fence: int | None) -> None:
        if worker_id is not None and execution_fence is not None:
            self.repository.assert_execution_fence(job_id, worker_id, execution_fence)

    async def run(
        self,
        job_id: str,
        initial_state: dict[str, Any],
        *,
        worker_id: str | None = None,
        execution_fence: int | None = None,
    ) -> None:
        if initial_state.get("workflow_type") == "research_gap":
            await ResearchGapJobService(self.repository).run(
                job_id,
                initial_state,
                worker_id=worker_id,
                execution_fence=execution_fence,
            )
            return
        settings = get_settings()
        event(
            logger,
            "job.started",
            state=initial_state,
            worker_id=worker_id,
            operation="run",
            config_resolved={
                "min_corpus_size": settings.litreview_min_corpus_size,
                "max_search_attempts": settings.litreview_max_search_attempts,
                "embedding_relevance_score": settings.litreview_embedding_relevance_score,
                "claim_validation_concurrency": settings.litreview_claim_validation_concurrency,
                "fulltext_chunks_per_paper": settings.litreview_fulltext_chunks_per_paper,
            },
        )
        async with AsyncPostgresSaver.from_conn_string(self.repository.database_url) as checkpointer:
            await checkpointer.setup()
            agent = uncompiled_graph.compile(checkpointer=checkpointer)
            config = _graph_config(job_id, "run")
            papers_found_so_far = len(initial_state.get("papers", []) or [])
            try:
                async for update in agent.astream(initial_state, config=config, stream_mode="updates"):
                    for node_name, values in update.items():
                        if not isinstance(values, dict):
                            continue
                        self._assert_fence(job_id, worker_id, execution_fence)
                        papers_found, papers_found_so_far = _paper_progress_counts(values, papers_found_so_far)
                        papers_in_update = len(values.get("papers") or []) if "papers" in values else 0
                        event(
                            logger,
                            "job.node_completed",
                            state={**initial_state, **values, "job_id": job_id},
                            node=node_name,
                            papers_found=papers_found,
                            papers_found_in_update=papers_in_update,
                            papers_found_total=papers_found_so_far,
                            status=values.get("status") or values.get("current_node") or "unknown",
                            keys=sorted(values.keys()),
                        )
                        self.repository.update_progress(
                            job_id,
                            node_name,
                            papers_found,
                            _progress_payload(values),
                        )

                snapshot = await agent.aget_state(config)
                state = snapshot.values if snapshot else {}
                self._assert_fence(job_id, worker_id, execution_fence)

                if state.get("error"):
                    event(
                        logger,
                        "job.failed",
                        state=state,
                        level=logging.ERROR,
                        error=state["error"],
                        failure_code="GRAPH_STATE_ERROR",
                        failed_stage=state.get("current_node"),
                    )
                    self.repository.fail_job(job_id, str(state["error"]))
                    return
                result = _result_from_state(state, list(snapshot.next) if snapshot else [])
                if snapshot and snapshot.next:
                    # Paused for HITL
                    event(
                        logger,
                        "job.paused",
                        state=state,
                        nodes=list(snapshot.next),
                        hitl_stage=result.get("hitl_stage"),
                    )
                    self.repository.complete_job(job_id, result)
                else:
                    # Finished without HITL pause (or already resumed)
                    final_status = state.get("status", "approved")
                    event(logger, "job.completed", state=state, final_status=final_status)
                    # Autonomous runs do not pause at a HITL node, so there is
                    # no earlier complete_job() call to persist result_json.
                    # Persist the final report before exposing the terminal
                    # status; otherwise the UI sees approved with no report.
                    self.repository.complete_job(job_id, _result_from_state(state), mark_waiting=False)
                    self.repository.finalize_job(job_id, state)
                    _persist_report_message(_result_from_state(state), job_id)
            except Exception as exc:
                logger.exception("job %s crashed in run()", job_id)
                if str(exc).startswith("WORKER_FENCE_LOST"):
                    return
                try:
                    self._assert_fence(job_id, worker_id, execution_fence)
                except RuntimeError:
                    logger.warning("job %s failure ignored because its worker fence was lost", job_id)
                    return
                event(
                    logger,
                    "job.failed",
                    state={**initial_state, "job_id": job_id},
                    level=logging.ERROR,
                    failure_code="JOB_RUNTIME_EXCEPTION",
                    failed_stage="run",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                self.repository.fail_job(job_id, f"{type(exc).__name__}: {exc}")

    async def resume(
        self, job_id: str, payload: dict, *, worker_id: str | None = None, execution_fence: int | None = None
    ) -> None:
        from langgraph.types import Command

        event(
            logger,
            "job.resumed",
            state={"job_id": job_id, "run_id": job_id},
            operation="resume",
            resume_payload=payload,
        )
        async with AsyncPostgresSaver.from_conn_string(self.repository.database_url) as checkpointer:
            agent = uncompiled_graph.compile(checkpointer=checkpointer)
            config = _graph_config(job_id, "resume")

            try:
                resume_state: dict[str, Any] = {"job_id": job_id, "run_id": job_id}
                papers_found_so_far = len(payload.get("papers", []) or [])
                async for update in agent.astream(Command(resume=payload), config=config, stream_mode="updates"):
                    for node_name, values in update.items():
                        if not isinstance(values, dict):
                            continue
                        self._assert_fence(job_id, worker_id, execution_fence)
                        papers_found, papers_found_so_far = _paper_progress_counts(values, papers_found_so_far)
                        papers_in_update = len(values.get("papers") or []) if "papers" in values else 0
                        event(
                            logger,
                            "job.node_completed",
                            state={**resume_state, **values, "job_id": job_id, "run_id": job_id},
                            node=node_name,
                            papers_found=papers_found,
                            papers_found_in_update=papers_in_update,
                            papers_found_total=papers_found_so_far,
                            status=values.get("status") or values.get("current_node") or "unknown",
                            keys=sorted(values.keys()),
                        )
                        resume_state.update(values)
                        self.repository.update_progress(
                            job_id,
                            node_name,
                            papers_found,
                            _progress_payload(values),
                        )

                snapshot = await agent.aget_state(config)
                state = snapshot.values if snapshot else {}
                self._assert_fence(job_id, worker_id, execution_fence)

                if state.get("error"):
                    event(
                        logger,
                        "job.failed",
                        state=state,
                        level=logging.ERROR,
                        error=state["error"],
                        failure_code="GRAPH_STATE_ERROR",
                        failed_stage=state.get("current_node"),
                    )
                    self.repository.fail_job(job_id, str(state["error"]))
                    return

                if snapshot and snapshot.next:
                    # Paused again for HITL after revisions
                    result = _result_from_state(state)
                    event(
                        logger,
                        "job.paused",
                        state=state,
                        nodes=list(snapshot.next),
                        hitl_stage=result.get("hitl_stage"),
                    )
                    self.repository.complete_job(job_id, result)
                else:
                    # Graph completed — finalize with full state to sync report JSON
                    event(
                        logger,
                        "job.completed",
                        state=state,
                        final_status=state.get("status", "approved"),
                        operation="resume",
                    )
                    # The persisted report may still be the earlier
                    # subquery/paper-gate snapshot. Save the complete graph
                    # state before exposing the terminal status.
                    self.repository.complete_job(job_id, _result_from_state(state), mark_waiting=False)
                    self.repository.finalize_job(job_id, state)
                    _persist_report_message(_result_from_state(state), job_id)

            except Exception as exc:
                logger.exception("job %s crashed in resume()", job_id)
                if str(exc).startswith("WORKER_FENCE_LOST"):
                    return
                try:
                    self._assert_fence(job_id, worker_id, execution_fence)
                except RuntimeError:
                    logger.warning("job %s resume failure ignored because its worker fence was lost", job_id)
                    return
                event(
                    logger,
                    "job.failed",
                    state={"job_id": job_id, "run_id": job_id},
                    level=logging.ERROR,
                    failure_code="JOB_RESUME_EXCEPTION",
                    failed_stage="resume",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                self.repository.fail_job(job_id, f"{type(exc).__name__}: {exc}")
