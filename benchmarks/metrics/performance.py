"""Performance and unit-economics metrics.

These are the numbers an investor reads first: how long one review takes, where
the time goes, and what it costs. Latency comes from the job's own node_trace,
so it is measured rather than estimated. Cost is only reported when the run
actually recorded token usage — an invented cost figure is worse than a missing
one, because it survives into a pitch deck unchallenged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from benchmarks.metrics.base import MetricResult

# Stages the user is actively waiting on. Queue time is excluded so the number
# describes the product, not how busy the machine was that afternoon.
_WAIT_EXCLUDED_NODES = {"queued", "waiting_for_subqueries", "waiting_for_papers", "waiting_for_review"}


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts))
    except ValueError:
        return None


def stage_durations(status: dict[str, Any]) -> list[tuple[str, float]]:
    """Per-node wall-clock seconds, derived from consecutive trace timestamps.

    node_trace records when each node *finished*, so a node's duration is the
    gap since the previous entry.
    """
    trace = status.get("node_trace") or []
    durations: list[tuple[str, float]] = []
    previous = None
    for event in trace:
        current = _parse(event.get("created_at"))
        if current is None:
            continue
        if previous is not None:
            durations.append((str(event.get("node")), (current - previous).total_seconds()))
        previous = current
    return durations


def total_latency(status: dict[str, Any]) -> MetricResult:
    """End-to-end wall clock for one review, excluding human-wait stages."""
    durations = stage_durations(status)
    if not durations:
        return MetricResult(
            name="Thời gian một lượt review", value=None, unit="seconds",
            unmeasured_reason="job không có node_trace",
        )
    active = [(node, seconds) for node, seconds in durations if node not in _WAIT_EXCLUDED_NODES]
    total = sum(seconds for _, seconds in active)
    return MetricResult(
        name="Thời gian một lượt review",
        value=total,
        unit="seconds",
        detail=(
            "Tổng thời gian máy chạy thật qua các chặng "
            "(đã trừ thời gian chờ người duyệt)."
        ),
    )


def bottleneck(status: dict[str, Any]) -> MetricResult:
    """The single slowest stage and how much of the run it owns.

    Tells an engineering team where one hour of optimization pays the most, and
    tells an investor whether the cost curve can realistically come down.
    """
    durations = [
        (node, seconds) for node, seconds in stage_durations(status)
        if node not in _WAIT_EXCLUDED_NODES
    ]
    if not durations:
        return MetricResult(
            name="Nút thắt cổ chai", value=None, unit="ratio",
            unmeasured_reason="job không có node_trace",
        )
    # One node can appear several times (retry loops); charge it the total.
    by_node: dict[str, float] = {}
    for node, seconds in durations:
        by_node[node] = by_node.get(node, 0.0) + seconds
    total = sum(by_node.values()) or 1.0
    slowest, slowest_seconds = max(by_node.items(), key=lambda item: item[1])
    return MetricResult(
        name="Nút thắt cổ chai",
        value=slowest_seconds / total,
        unit="ratio",
        # Intentionally no numerator/denominator: these are seconds-per-run,
        # not counts. _mean_metric sums numerators across runs when both fields
        # are present, which would produce total_seconds_run1 / total_seconds_run2
        # — a meaningless fraction. Omitting them forces _mean_metric to fall
        # through to statistics.mean(), which is the correct aggregation for
        # per-run ratios.
        detail=f"Chặng chậm nhất của lượt chạy: `{slowest}` (tỷ lệ phần thời gian thể hiện ở giá trị chỉ số).",
    )


def time_to_first_output(status: dict[str, Any]) -> MetricResult:
    """Seconds until the user has something real to read.

    Distinct from total latency: it measures the wait a user actually feels
    before the product stops looking empty.
    """
    trace = status.get("node_trace") or []
    if not trace:
        return MetricResult(
            name="Thời gian tới kết quả đầu tiên", value=None, unit="seconds",
            unmeasured_reason="job không có node_trace",
        )
    start = _parse(trace[0].get("created_at"))
    first = next(
        (event for event in trace if (event.get("papers_found") or 0) > 0),
        None,
    )
    if start is None or first is None:
        return MetricResult(
            name="Thời gian tới kết quả đầu tiên", value=None, unit="seconds",
            unmeasured_reason="lượt chạy chưa bao giờ có bài báo nào",
        )
    moment = _parse(first.get("created_at"))
    if moment is None:
        return MetricResult(
            name="Thời gian tới kết quả đầu tiên", value=None, unit="seconds",
            unmeasured_reason="thiếu mốc thời gian",
        )
    return MetricResult(
        name="Thời gian tới kết quả đầu tiên",
        value=(moment - start).total_seconds(),
        unit="seconds",
        detail=f"Tới chặng `{first.get('node')}` là người dùng đã có bài báo để đọc.",
    )


def cost_per_review(status: dict[str, Any], usage: dict[str, Any] | None = None) -> MetricResult:
    """USD for one completed review — only when token usage was recorded.

    ``usage`` is supplied by the caller (e.g. read from Langfuse or a local
    token counter). When it is absent this returns *unmeasured* on purpose:
    a plausible-looking estimate is the single easiest number to get wrong in
    a pitch, and the hardest to walk back.
    """
    if not usage or not usage.get("total_cost_usd"):
        return MetricResult(
            name="Chi phí một lượt review",
            value=None,
            unit="usd",
            unmeasured_reason=(
                "hệ thống chưa ghi token/chi phí — bật Langfuse (LANGFUSE_PUBLIC_KEY/"
                "LANGFUSE_SECRET_KEY) hoặc truyền usage vào để đo thật"
            ),
        )
    return MetricResult(
        name="Chi phí một lượt review",
        value=float(usage["total_cost_usd"]),
        unit="usd",
        numerator=usage.get("total_tokens"),
        detail="Đo từ token/chi phí thật của các lời gọi LLM mà Langfuse ghi nhận cho lượt chạy này.",
    )


def human_time_saved(
    status: dict[str, Any],
    *,
    manual_minutes: float | None,
) -> MetricResult:
    """Time saved versus a human doing the same task.

    ``manual_minutes`` must come from a stated, defensible source (a measured
    internal trial, or a cited study) and is passed in explicitly. It is never
    guessed here, because this is the number most likely to be quoted back at
    the team later.
    """
    if manual_minutes is None:
        return MetricResult(
            name="Thời gian tiết kiệm so với làm tay",
            value=None, unit="ratio",
            unmeasured_reason=(
                "chưa có baseline thủ công đo thật — cần bấm giờ một researcher "
                "làm cùng chủ đề, cùng số bài, rồi truyền vào"
            ),
        )
    latency = total_latency(status)
    if not latency.measured:
        return MetricResult(
            name="Thời gian tiết kiệm so với làm tay",
            value=None, unit="ratio",
            unmeasured_reason="chưa đo được thời gian chạy",
        )
    assert latency.value is not None
    agent_minutes = latency.value / 60.0
    saved = max(0.0, (manual_minutes - agent_minutes) / manual_minutes)
    return MetricResult(
        name="Thời gian tiết kiệm so với làm tay",
        value=saved,
        unit="ratio",
        numerator=round(manual_minutes - agent_minutes, 1),
        denominator=round(manual_minutes, 1),
        detail=(
            "So sánh thời gian agent với baseline thủ công do người dùng cung cấp "
            "(baseline đo thật, không phải ước lượng của hệ thống)."
        ),
    )
