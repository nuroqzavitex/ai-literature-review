"""Turn saved run artifacts into metrics and a two-layer report.

Layer 1 is the executive table: a handful of numbers with an explicit target
and a verdict. Layer 2 is the audit trail: the numerator/denominator behind
every number and the concrete items that failed.

Both layers come from the same computation. There is no separate "presentation
number" — the figure in the summary is the figure a reviewer can drill into,
which is the only reason a benchmark is worth anything to someone deciding
whether to trust the product.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.metrics import coverage, performance, reliability, trust
from benchmarks.metrics.base import MetricResult


@dataclass(frozen=True)
class Target:
    """A stated bar with the direction that counts as good.

    Targets live in code, not in prose, so a run either clears them or it does
    not — nobody gets to reinterpret a number after seeing it.
    """

    value: float
    higher_is_better: bool
    rationale: str

    def verdict(self, metric: MetricResult) -> str:
        if not metric.measured:
            return "⚪ chưa đo"
        assert metric.value is not None
        ok = metric.value >= self.value if self.higher_is_better else metric.value <= self.value
        return "🟢 đạt" if ok else "🔴 chưa đạt"

    def describe(self, unit: str) -> str:
        arrow = "≥" if self.higher_is_better else "≤"
        shown = f"{self.value * 100:.0f}%" if unit == "ratio" else f"{self.value:g}"
        return f"{arrow} {shown}"


TARGETS: dict[str, Target] = {
    "Trích dẫn bịa (fabricated citations)": Target(
        0.0, False, "Một trích dẫn bịa là đủ để nhà nghiên cứu bỏ công cụ. Không có ngưỡng chấp nhận được nào khác 0."),
    "Citation review trỏ tới paper đã lấy": Target(
        1.0, True, "Bất kỳ citation nào trong bài review cuối không thuộc corpus là một đường dẫn nguồn không thể kiểm toán."),
    "Đoạn review có evidence truy vết được": Target(
        0.95, True, "Đoạn factual không nối được tới quote evidence là điểm mù: có thể đúng, nhưng chưa chứng minh được bằng artifact."),
    "Claim có bằng chứng": Target(
        1.0, True, "Claim đã đánh dấu hợp lệ mà không có trích dẫn là khẳng định trần, đội lốt đã kiểm chứng."),
    "Kiểm soát âm (chủ đề vô nghĩa)": Target(
        1.0, True, "Hệ thống phải biết nói 'không có gì'. Đây là ranh giới giữa công cụ nghiên cứu và máy sinh văn bản."),
    "Trích dẫn kiểm chứng được (verbatim)": Target(
        0.95, True, "Quote phải khớp nguyên văn nguồn; sai lệch nhỏ vẫn là diễn giải lại lời tác giả."),
    "Độ phủ chủ đề (theme recall)": Target(
        0.7, True, "Dưới ngưỡng này, bản review bỏ sót mảng kiến thức mà chuyên gia coi là bắt buộc."),
    "Tỷ lệ chạy thành công": Target(
        0.95, True, "Dưới 95% là gánh nặng vận hành: cứ 20 lượt có hơn 1 lượt phải xử lý tay."),
    "Bài báo được dùng thật": Target(
        0.5, True, "Tải 20 bài chỉ dùng 3 nghĩa là đang trả tiền cho 17 bài vô ích."),
}


def load_run(run_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load run records and their artifacts from a results directory."""
    runs = json.loads((run_dir / "runs.json").read_text(encoding="utf-8"))
    artifacts: list[dict[str, Any]] = []
    for record in runs:
        name = record.get("artifact")
        if not name:
            artifacts.append({})
            continue
        path = run_dir / name
        artifacts.append(
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )
    return runs, artifacts


def _mean_metric(name: str, metrics: list[MetricResult]) -> MetricResult:
    """Average a metric across runs, keeping the audit trail intact.

    Only measured runs contribute. Summing numerators rather than averaging
    percentages avoids letting a run with 2 claims outweigh one with 40.
    """
    measured = [m for m in metrics if m.measured]
    if not measured:
        reasons = {m.unmeasured_reason for m in metrics if m.unmeasured_reason}
        return MetricResult(
            name=name, value=None, unit=metrics[0].unit if metrics else "ratio",
            unmeasured_reason="; ".join(sorted(r for r in reasons if r)) or "không có dữ liệu",
        )
    unit = measured[0].unit
    failures = [f for m in measured for f in m.failures]
    # The first run's detail often narrates that run's specifics. Keep the
    # method text but mark the aggregation, so a per-run figure can never sit
    # next to the pooled number and read as its explanation.
    detail = measured[0].detail
    if len(measured) > 1:
        detail = (f"{detail} " if detail else "") + f"(Số trên gộp từ {len(measured)} lượt chạy.)"
    if unit == "ratio" and all(m.denominator is not None for m in measured):
        numerator = sum(m.numerator or 0 for m in measured)
        denominator = sum(m.denominator or 0 for m in measured)
        if denominator:
            return MetricResult(
                name=name, value=numerator / denominator, unit="ratio",
                numerator=numerator, denominator=denominator,
                detail=detail, failures=failures,
            )
    return MetricResult(
        name=name,
        value=statistics.mean(m.value for m in measured if m.value is not None),
        unit=unit,
        detail=detail,
        failures=failures,
    )


def compute_metrics(runs: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute every metric family from artifacts. Pure — no network, no clock."""
    positive_trust: dict[str, list[MetricResult]] = {}
    positive_coverage: dict[str, list[MetricResult]] = {}
    perf: dict[str, list[MetricResult]] = {}
    negative_controls: list[MetricResult] = []
    attrition: list[dict[str, Any]] = []
    core_runs: list[dict[str, Any]] = []
    unsupported_domain_runs: list[dict[str, Any]] = []

    for record, artifact in zip(runs, artifacts, strict=True):
        result = artifact.get("result") or {}
        status = artifact.get("status") or {}
        entry = record.get("dataset_entry") or {}
        is_negative = record.get("kind") == "negative_control"

        if entry.get("evaluation_scope", "core") == "unsupported_domain":
            unsupported_domain_runs.append({
                "topic_id": record.get("topic_id"),
                "topic": record.get("topic"),
                "outcome": record.get("outcome"),
                "reason": entry.get("scope_reason") or "domain chưa có source/corpus phù hợp",
            })
            continue

        core_runs.append(record)

        if is_negative:
            negative_controls.append(trust.negative_control(
                papers=int(record.get("papers") or 0),
                valid_claims=int(record.get("valid_claims") or 0),
                pipeline_outcome=str(record.get("outcome") or ""),
                # An infra crash that yielded empty output is NOT a pass — the
                # runner already classified which refusions were intentional.
                refusal_kind=str(record.get("refusal_kind")) if record.get("refusal_kind") else None,
            ))
            continue
        if record.get("outcome") != "completed":
            continue

        for metric in (
            trust.fabricated_citation_rate(result),
            trust.review_citation_validity(result),
            trust.review_evidence_coverage(result),
            trust.quote_verifiability(result),
            trust.claim_grounding_rate(result),
            trust.evidence_density(result),
        ):
            positive_trust.setdefault(metric.name, []).append(metric)

        for metric in (
            coverage.theme_recall(result, entry.get("expected_themes") or []),
            coverage.fulltext_evidence_ratio(result),
            *coverage.paper_ingestion_metrics(result),
            coverage.corpus_yield(result, requested=int(entry.get("max_results") or 0)),
            coverage.citation_reuse(result),
        ):
            positive_coverage.setdefault(metric.name, []).append(metric)

        for metric in (
            performance.total_latency(status),
            performance.time_to_first_output(status),
            performance.bottleneck(status),
            performance.human_time_saved(status, manual_minutes=entry.get("manual_baseline_minutes")),
            performance.cost_per_review(status, usage=record.get("usage")),
        ):
            perf.setdefault(metric.name, []).append(metric)

        rows = coverage.pipeline_attrition(status)
        if rows:
            attrition.append({"topic": record.get("topic"), "stages": rows})

    aggregated = {
        name: _mean_metric(name, items)
        for group in (positive_trust, positive_coverage, perf)
        for name, items in group.items()
    }
    if negative_controls:
        clean = sum(1 for m in negative_controls if m.value == 1.0)
        aggregated["Kiểm soát âm (chủ đề vô nghĩa)"] = MetricResult(
            name="Kiểm soát âm (chủ đề vô nghĩa)",
            value=clean / len(negative_controls),
            unit="ratio",
            numerator=clean,
            denominator=len(negative_controls),
            detail="Tỷ lệ chủ đề vô nghĩa mà hệ thống đúng mực trả về rỗng.",
            failures=[f for m in negative_controls for f in m.failures],
        )

    aggregated["Tỷ lệ chạy thành công"] = reliability.success_rate(core_runs)
    aggregated["Độ trễ p50 / p95"] = reliability.latency_spread(core_runs)
    aggregated["Độ ổn định đầu ra"] = reliability.output_consistency(core_runs)

    # None khi verify-sources chưa chạy cho thư mục này — metric vắng mặt
    # thay vì "chưa đo" hàng loạt ở các run dir cũ.
    resolved_sources = trust.source_resolvability(core_runs)
    if resolved_sources is not None:
        aggregated["Nguồn tra cứu được thật"] = resolved_sources

    return {
        "metrics": aggregated,
        "failure_taxonomy": reliability.failure_taxonomy(core_runs),
        "attrition": attrition,
        "unsupported_domain_runs": unsupported_domain_runs,
    }


_HEADLINE = [
    "Trích dẫn bịa (fabricated citations)",
    "Nguồn tra cứu được thật",
    "Citation review trỏ tới paper đã lấy",
    "Đoạn review có evidence truy vết được",
    "Kiểm soát âm (chủ đề vô nghĩa)",
    "Claim có bằng chứng",
    "Trích dẫn kiểm chứng được (verbatim)",
    "Độ phủ chủ đề (theme recall)",
    "Đủ metadata ingestion cho paper",
    "Paper có full text",
    "Paper chỉ có abstract (không khả dụng)",
    "Paper fallback do lỗi ingestion",
    "Tỷ lệ chạy thành công",
    "Thời gian một lượt review",
    "Chi phí một lượt review",
]


def render_markdown(run_dir: Path, runs: list[dict[str, Any]], computed: dict[str, Any]) -> str:
    metrics: dict[str, MetricResult] = computed["metrics"]
    lines: list[str] = []
    add = lines.append

    completed = sum(1 for r in runs if r.get("outcome") == "completed")
    refused = sum(1 for r in runs if r.get("outcome") == "refused")
    empty = sum(1 for r in runs if r.get("outcome") == "empty_result")
    infra_errors = sum(
        1 for r in runs
        if r.get("outcome") == "refused" and r.get("refusal_kind") == "infrastructure_error"
    )
    add(f"# Benchmark — {run_dir.name}")
    add("")
    add(f"> Sinh lúc {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"{len(runs)} lượt chạy ({completed} hoàn tất"
        + (f", {refused} từ chối đúng thiết kế" if refused else "")
        + (f", {empty} chủ đề thật trả rỗng" if empty else "")
        + (f" — ⚠️ {infra_errors} lượt có thể là lỗi hạ tầng, không phải từ chối có chủ đích" if infra_errors else "")
        + f") · artifact thô: `{run_dir}`")
    add("")

    unsupported_domain_runs = computed.get("unsupported_domain_runs") or []
    if unsupported_domain_runs:
        add("> **Ngoài scope score core**: "
            f"{len(unsupported_domain_runs)} lượt thuộc domain chưa có source/corpus phù hợp; "
            "artifact vẫn giữ để audit nhưng không tính vào metric core.")
        add("")

    # Run environment snapshot — written by runner.py before the first API call.
    # Shown in the report so any number can be traced back to the exact commit
    # and provider config that produced it.
    env_path = run_dir / "run_env.json"
    if env_path.exists():
        try:
            env = json.loads(env_path.read_text(encoding="utf-8"))
            commit = str(env.get("git_commit", "unknown"))
            dirty = " ⚠️ (working tree dirty)" if env.get("git_dirty") else ""
            health = env.get("health_response") or {}
            model_info = (
                f" · model={health.get('model') or health.get('version') or '?'}"
                if any(k in health for k in ("model", "version"))
                else ""
            )
            add(f"> **Môi trường**: commit `{commit[:12]}`{dirty}{model_info} · "
                f"API `{env.get('base_url', '?')}` · {env.get('timestamp_utc', '?')[:19]} UTC")
            add("")
        except Exception:
            pass  # corrupt env file should not break the report

    corpus_path = run_dir / "corpus_snapshot.json"
    if corpus_path.exists():
        try:
            corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
            summary = corpus.get("summary") or {}
            fingerprint = str((corpus.get("dataset") or {}).get("sha256") or "")
            add(
                f"> **Corpus freeze**: {summary.get('papers_total', 0)} paper "
                f"({summary.get('papers_unique', 0)} unique) · dataset `{fingerprint[:12] or '?'}` · "
                f"`{corpus_path.name}`"
            )
            add("")
        except Exception:
            pass  # corrupt corpus file should not break the report

    add("Mọi con số dưới đây tính trực tiếp từ artifact thô đã lưu. "
        "Tái lập bằng: `python -m benchmarks report " + str(run_dir) + "`")
    add("")

    add("## 1. Tóm tắt điều hành")
    add("")
    add("| Chỉ số | Kết quả | Mục tiêu | Đánh giá |")
    add("|---|---|---|---|")
    for name in _HEADLINE:
        metric = metrics.get(name)
        if metric is None:
            continue
        target = TARGETS.get(name)
        add(
            f"| {name} | **{metric.format_value()}** | "
            f"{target.describe(metric.unit) if target else '—'} | "
            f"{target.verdict(metric) if target else '—'} |"
        )
    add("")

    unmeasured = [m for m in metrics.values() if not m.measured]
    if unmeasured:
        add("### Chưa đo được — nêu rõ thay vì bỏ trống")
        add("")
        for metric in unmeasured:
            add(f"- **{metric.name}**: {metric.unmeasured_reason}")
        add("")

    add("## 2. Vết kiểm toán từng chỉ số")
    add("")
    for name, metric in sorted(metrics.items()):
        add(f"### {name}")
        add("")
        add(f"- Kết quả: **{metric.format_value()}**")
        if metric.detail:
            add(f"- Cách đo: {metric.detail}")
        target = TARGETS.get(name)
        if target:
            add(f"- Vì sao đặt mục tiêu {target.describe(metric.unit)}: {target.rationale}")
        if metric.failures:
            add(f"- Số mục không đạt: **{len(metric.failures)}** (liệt kê tối đa 5):")
            for failure in metric.failures[:5]:
                bits = " · ".join(f"{k}={v}" for k, v in failure.items() if k != "reason")
                add(f"  - {failure.get('reason', '')} — {bits}")
        add("")

    taxonomy = computed["failure_taxonomy"]
    if taxonomy:
        add("## 3. Phân loại lỗi")
        add("")
        add("| Nguyên nhân | Số lượt | Chủ đề |")
        add("|---|---:|---|")
        for row in taxonomy:
            add(f"| `{row['cause']}` | {row['count']} | {', '.join(t[:40] for t in row['topics'])} |")
        add("")

    if unsupported_domain_runs:
        add("## 4. Lượt ngoài scope core")
        add("")
        add("Các lượt này không dùng để kết luận chất lượng hệ thống hiện tại.")
        add("")
        add("| Topic | Outcome | Lý do |")
        add("|---|---|---|")
        for item in unsupported_domain_runs:
            add(f"| {item['topic']} | `{item['outcome']}` | {item['reason']} |")
        add("")

    attrition = computed["attrition"]
    if attrition:
        add("## 5. Hao hụt dữ liệu theo chặng")
        add("")
        add("Cho thấy dữ liệu rơi rụng ở đâu — chặng nào mất nhiều nhất là chỗ đáng sửa trước.")
        add("")
        for item in attrition[:3]:
            add(f"**{item['topic'][:60]}**")
            add("")
            add("| Chặng | Vào | Ra | Mất | Lý do |")
            add("|---|---:|---:|---:|---|")
            for stage in item["stages"]:
                loss = stage.get("loss_rate")
                dropped = ", ".join(f"{k}={v}" for k, v in (stage.get("dropped") or {}).items())
                add(
                    f"| {stage['stage']} | {stage.get('received', '—')} | {stage.get('emitted', '—')} | "
                    f"{f'{loss * 100:.0f}%' if loss is not None else '—'} | {dropped or '—'} |"
                )
            add("")

    add("## 6. Cách đọc bản báo cáo này")
    add("")
    add("- **🔴 chưa đạt** không có nghĩa sản phẩm hỏng — nó chỉ ra đúng chỗ cần đầu tư tiếp.")
    add("- **⚪ chưa đo** là trung thực có chủ đích: chỉ số đó cần dữ liệu mà lượt chạy này "
        "không có (ví dụ baseline thủ công, hoặc token usage chưa bật). Không suy đoán số thay thế.")
    add("- Mọi tỷ lệ đều kèm tử số/mẫu số để tự kiểm, và mọi mục không đạt đều liệt kê được.")
    add("- Hai chỉ số thời gian đo khác nhau: **Thời gian một lượt review** là thời gian máy "
        "chạy (đã trừ chờ người duyệt); **Độ trễ p50/p95** là wall clock từ lúc tạo job. "
        "Trừ nhau ra thời gian chờ, không phải sai số.")
    return "\n".join(lines)
