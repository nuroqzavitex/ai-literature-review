"""Small helpers for consistent, searchable application event logs."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from hashlib import sha256
from typing import Any

from src.config import get_settings

_SENSITIVE_FIELD_MARKERS = ("api_key", "authorization", "password", "secret", "token")
_VERBOSE_FIELD_MARKERS = (
    "prompt",
    "abstract",
    "full_text",
    "content",
    "message",
    "feedback",
    "payload",
    "error",
)
_MAX_VALUE_LENGTH = 512


def failure_code(error: BaseException | str) -> str:
    """Map an exception to a stable, aggregation-friendly failure code."""
    message = str(error).lower()
    if "worker_fence_lost" in message:
        return "WORKER_FENCE_LOST"
    if any(marker in message for marker in ("429", "rate limit", "resource_exhausted")):
        return "PROVIDER_RATE_LIMITED"
    if any(marker in message for marker in ("401", "403", "api key", "unauthorized", "forbidden")):
        return "PROVIDER_AUTH_FAILED"
    if any(marker in message for marker in ("timeout", "connection", "network")):
        return "UPSTREAM_UNAVAILABLE"
    if any(marker in message for marker in ("missing or untraceable citations", "citation", "supporting_paper_ids")):
        return "CITATION_VALIDATION_FAILED"
    if any(marker in message for marker in ("validation", "json", "schema", "parser")):
        return "STRUCTURED_OUTPUT_INVALID"
    return "UNEXPECTED_EXCEPTION"


def _safe_value(value: Any, *, key: str = "") -> Any:
    """Keep structured logs bounded and prevent user content/secrets from leaking."""
    key_lower = key.lower()
    if any(marker in key_lower for marker in _SENSITIVE_FIELD_MARKERS):
        return "[REDACTED]"
    if any(marker in key_lower for marker in _VERBOSE_FIELD_MARKERS):
        return {"redacted": True, "type": type(value).__name__}
    if isinstance(value, dict):
        return {
            str(child_key): _safe_value(child_value, key=str(child_key)) for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        return [_safe_value(item, key=key) for item in values[:20]] + (["[TRUNCATED]"] if len(values) > 20 else [])
    if isinstance(value, str):
        return value if len(value) <= _MAX_VALUE_LENGTH else f"{value[:_MAX_VALUE_LENGTH]}…[TRUNCATED]"
    return value


def job_fields(state: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """Return stable correlation fields without logging prompts or abstracts."""
    state = state or {}
    job_id = state.get("job_id") or state.get("thread_id") or "adhoc"
    return {
        "job_id": job_id,
        "run_id": state.get("run_id") or job_id,
        "request_id": state.get("request_id"),
        "execution_mode": state.get("execution_mode", "review"),
        "attempt": state.get("search_attempt", 0),
        **extra,
    }


def event(
    logger: logging.Logger,
    name: str,
    *,
    state: dict[str, Any] | None = None,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Emit one redacted JSON event directly to the process stream.

    Writing to stderr and flushing immediately keeps worker events realtime
    through Docker's line-oriented rotating tee. Normal logger handlers can
    buffer or filter records before they reach ``worker.log``.
    """
    raw_payload = {"event": name, **job_fields(state, **fields)}
    # Never sample away warning/error events.  For high-volume INFO/DEBUG
    # events use a stable hash so all events for the same job make a consistent
    # keep/drop decision and dashboards are not skewed by random sampling.
    sample_rate = get_settings().observability_event_sample_rate
    # Step events are operational progress and must never disappear from the
    # realtime worker log, even when general INFO event sampling is enabled.
    if name not in {"agent.step", "job.node_completed"} and level < logging.WARNING and sample_rate < 1:
        sample_key = f"{raw_payload['job_id']}:{raw_payload['run_id']}:{name}"
        sample_value = int(sha256(sample_key.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
        if sample_value >= sample_rate:
            return
    payload = _safe_value(raw_payload)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    line = (
        f"{datetime.now().astimezone().isoformat(timespec='milliseconds')} "
        f"{logging.getLevelName(level)} [{logger.name}] event={name} {serialized}\n"
    )
    sys.stderr.write(line)
    sys.stderr.flush()


def id_summary(values: list[Any], *, sample_size: int = 10) -> dict[str, Any]:
    """Keep IDs inspectable while bounding log volume."""
    ids = [str(value) for value in values if value is not None]
    return {
        "count": len(ids),
        "sample": ids[:sample_size],
        "sha256": sha256("\n".join(ids).encode("utf-8")).hexdigest(),
    }


def paper_summary(paper: dict[str, Any]) -> dict[str, Any]:
    """Return diagnostic paper metadata while excluding abstract and full text."""
    return {
        "paper_id": paper.get("paper_id"),
        "source": paper.get("source", "unknown"),
        "title": paper.get("title", ""),
        "year": paper.get("year"),
        "embedding_score": paper.get("relevance_score"),
        "embedding_pass": paper.get("relevance_score") is not None,
        "relevance_label": paper.get("relevance_label"),
    }
