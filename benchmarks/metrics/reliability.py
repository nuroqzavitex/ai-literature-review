"""Reliability metrics — aggregated across many runs, not one lucky demo.

Single-run numbers sell a demo; these numbers decide whether a team can put the
product in front of customers. They answer: does it finish, how often does it
fail and why, and how wide is the spread between a good run and a bad one.
"""

from __future__ import annotations

import statistics
from typing import Any

from benchmarks.metrics.base import MetricResult, ratio


def success_rate(runs: list[dict[str, Any]]) -> MetricResult:
    """Share of *positive* runs that finished with a usable report.

    Negative controls are excluded on purpose: they are designed to end with
    no output, so counting them here would make a correctly-refusing system
    look unreliable.
    """
    positive = [r for r in runs if r.get("kind") != "negative_control"]
    completed = [r for r in positive if r.get("outcome") == "completed"]
    failures = [
        {
            "topic": r.get("topic"),
            "outcome": r.get("outcome"),
            "reason": str(r.get("error") or "không rõ")[:200],
        }
        for r in positive if r.get("outcome") != "completed"
    ]
    return ratio(
        "Tỷ lệ chạy thành công",
        numerator=len(completed),
        denominator=len(positive),
        detail="Tỷ lệ lượt chạy chủ đề THẬT ra được báo cáo dùng được (không tính kiểm soát âm).",
        failures=failures,
        empty_reason="chưa có lượt chạy chủ đề thật nào",
    )


def failure_taxonomy(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Failures grouped by cause, most frequent first.

    An aggregate failure rate tells you there is a problem; this tells you
    whether it is one bug or fifteen, which is the difference between a
    fixable product and a fragile one.
    """
    buckets: dict[str, list[str]] = {}
    for run in runs:
        # "refused" is a correct negative-control outcome, not a defect.
        if run.get("outcome") in {"completed", "refused"}:
            continue
        cause = str(run.get("error_class") or run.get("outcome") or "unknown")
        buckets.setdefault(cause, []).append(str(run.get("topic", "")))
    return sorted(
        ({"cause": cause, "count": len(topics), "topics": topics[:5]} for cause, topics in buckets.items()),
        key=lambda row: row["count"],
        reverse=True,
    )


def latency_spread(runs: list[dict[str, Any]]) -> MetricResult:
    """p50 and p95 wall clock across runs.

    p95 is the number that sets a timeout and shapes the support burden; a
    median alone hides the runs that make users give up.
    """
    values = sorted(
        float(r["latency_seconds"]) for r in runs
        if r.get("outcome") == "completed" and r.get("latency_seconds") is not None
    )
    if not values:
        return MetricResult(
            name="Độ trễ p50 / p95", value=None, unit="seconds",
            unmeasured_reason="chưa có lượt chạy thành công nào có số đo",
        )
    p50 = statistics.median(values)
    # Nearest-rank p95: with few samples this is the honest reading, where an
    # interpolated value would imply more precision than N runs can support.
    p95 = values[min(len(values) - 1, max(0, round(0.95 * len(values)) - 1))]
    return MetricResult(
        name="Độ trễ p50 / p95",
        value=p50,
        unit="seconds",
        detail=(
            f"p50 = {p50:.0f}s · p95 = {p95:.0f}s · nhanh nhất {values[0]:.0f}s · "
            f"chậm nhất {values[-1]:.0f}s (n={len(values)}). "
            "Đây là wall clock từ lúc tạo job (bao gồm cả chờ) — khác với "
            "'Thời gian một lượt review' đã trừ các chặng chờ người duyệt."
        ),
    )


def output_consistency(runs: list[dict[str, Any]]) -> MetricResult:
    """How stable the output size is when the same topic is run repeatedly.

    Reported as 1 - (stdev / mean) of the valid-claim count per topic. A
    research tool that returns 12 claims one run and 3 the next is not
    trustworthy even when every individual claim is well grounded — and this
    is exactly the failure that a single-run benchmark cannot see.
    """
    by_topic: dict[str, list[int]] = {}
    for run in runs:
        if run.get("outcome") != "completed" or run.get("valid_claims") is None:
            continue
        by_topic.setdefault(str(run.get("topic")), []).append(int(run["valid_claims"]))

    repeated = {topic: counts for topic, counts in by_topic.items() if len(counts) >= 2}
    if not repeated:
        return MetricResult(
            name="Độ ổn định đầu ra", value=None, unit="ratio",
            unmeasured_reason="cần chạy lặp cùng một chủ đề ≥2 lần (--repeat 3)",
        )
    scores: list[float] = []
    detail_rows: list[str] = []
    for topic, counts in repeated.items():
        mean = statistics.mean(counts)
        if mean == 0:
            continue
        cv = statistics.pstdev(counts) / mean
        scores.append(max(0.0, 1 - cv))
        detail_rows.append(f"{topic[:30]}: {counts}")
    if not scores:
        return MetricResult(
            name="Độ ổn định đầu ra", value=None, unit="ratio",
            unmeasured_reason="mọi lượt lặp đều ra 0 claim",
        )
    return MetricResult(
        name="Độ ổn định đầu ra",
        value=statistics.mean(scores),
        unit="ratio",
        detail="Càng gần 100% càng ít dao động giữa các lần chạy. " + " · ".join(detail_rows),
    )
