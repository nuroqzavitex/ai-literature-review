"""RAGAS adapter for saved literature-source evaluation artifacts.

RAGAS is an LLM-as-judge layer, not a replacement for the deterministic
citation and evidence checks in :mod:`benchmarks.metrics`. This adapter
intentionally reads only the final literature review and the evidence quotes
attached to its final claims. It never passes paper abstracts or intermediate
claim text as the answer: doing that would let retrieval or claim extraction
grade itself instead of the review the user receives.

New runs persist bounded ``retrieval_traces`` with raw ranked chunks for each
retrieval call.  This adapter continues to score the final evidence set until
reviewed chunk-level gold labels exist; it must not manufacture chunk relevance
from a system's own ranking. A reviewed paper-level gold file may supply a
human-authored ``reference_answer`` to enable Context Precision and Recall.
Without it, only Faithfulness is run and the other metrics stay unmeasured.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
import sys
import types
from typing import Any

from benchmarks.gold import GoldTopic, PaperGoldOutcome
from benchmarks.metrics import trust
from benchmarks.metrics.base import MetricResult

RAGAS_TARGETS = {
    "faithfulness": 0.90,
    "context_precision": 0.80,
    "context_recall": 0.80,
}

_LABELS = {
    "faithfulness": "RAGAS Faithfulness",
    "context_precision": "RAGAS Context Precision",
    "context_recall": "RAGAS Context Recall",
}


@dataclass(frozen=True)
class RagasSample:
    """The minimum RAGAS input reconstructed from one saved artifact."""

    topic_id: str
    user_input: str
    response: str
    retrieved_contexts: list[str]
    reference: str | None = None


@dataclass
class RagasOutcome:
    """Scores and per-metric errors for a single benchmark topic."""

    topic_id: str
    scores: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    @property
    def judged(self) -> bool:
        return bool(self.scores)

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "scores": self.scores,
            "reasons": self.reasons,
            "error": self.error,
        }


RagasScorer = Callable[[RagasSample], Awaitable[RagasOutcome]]


def answer_text(result: dict[str, Any]) -> str:
    """Ghép bài review thành một khối văn bản — đúng thứ giám khảo phải đọc.

    Chỉ lấy literature review do hệ thống SINH RA. Abstract của các bài đã tải
    và claim trung gian không được đưa vào: dán chúng vào sẽ khiến retrieval
    hoặc claim extractor tự chấm điểm thay cho bài review người dùng nhận.
    """
    review = result.get("literature_review") or {}
    parts = [
        str(review.get("title", "")),
        str(review.get("abstract", "")),
        str(review.get("introduction", "")),
    ]
    for section in review.get("sections") or []:
        parts.append(str(section.get("title", "")))
        parts.extend(str(p) for p in section.get("paragraphs") or [])
    parts += [str(review.get("conclusion", "")), str(review.get("limitations", ""))]
    return "\n\n".join(p for p in parts if p.strip()).strip()


def sample_from_artifact(
    record: dict[str, Any], artifact: dict[str, Any], *, gold: GoldTopic | None = None,
) -> tuple[RagasSample | None, str | None]:
    """Build an evaluation sample without manufacturing absent ground truth."""
    result = artifact.get("result") or {}
    entry = record.get("dataset_entry") or {}
    topic_id = str(record.get("topic_id") or "unknown")
    user_input = str(entry.get("topic") or record.get("topic") or "").strip()
    response = answer_text(result)

    if not user_input:
        return None, "thiếu topic/câu hỏi trong run record"
    if not response:
        return None, "artifact không có bản review hoặc claim để chấm"

    contexts: list[str] = []
    seen: set[str] = set()
    for claim in result.get("claims") or []:
        if claim.get("validation_status") != "valid":
            continue
        for evidence in claim.get("evidence") or []:
            quote = str(evidence.get("quote") or "").strip()
            if not quote or quote in seen:
                continue
            seen.add(quote)
            paper_id = str(evidence.get("paper_id") or "unknown")
            contexts.append(f"[{paper_id}] {quote}")

    if not contexts:
        return None, "artifact không có evidence quote của claim hợp lệ"

    # ``reference_answer`` in the gold file is human-reviewed and takes
    # precedence.  The dataset fallback keeps old artifacts evaluable, but new
    # paper-level runs should keep reference data next to their frozen gold.
    reference = gold.reference_answer if gold else None
    if reference is None:
        reference = str(entry.get("reference_answer") or "").strip() or None
    return RagasSample(
        topic_id=topic_id,
        user_input=user_input,
        response=response,
        retrieved_contexts=contexts,
        reference=reference,
    ), None


async def default_scorer(sample: RagasSample) -> RagasOutcome:
    """Score one sample using the project's configured LangChain LLM.

    Imports are deliberately late: ``python -m benchmarks selftest`` remains
    offline and can run in environments where RAGAS and application secrets do
    not exist.  RAGAS v0.4's Collections API returns ``MetricResult`` objects;
    the adapter stores their scalar values and optional explanations.
    """
    try:
        # RAGAS 0.4.3 still imports this removed LangChain compatibility
        # module, even though the Collections metrics below do not use it for
        # an OpenAI-compatible judge.  Supply only the import-time symbol.
        legacy_vertexai = "langchain_community.chat_models.vertexai"
        if legacy_vertexai not in sys.modules:
            shim = types.ModuleType(legacy_vertexai)
            shim.ChatVertexAI = type("ChatVertexAI", (), {})
            sys.modules[legacy_vertexai] = shim

        from openai import AsyncOpenAI
        from ragas.llms import llm_factory
        from ragas.metrics.collections import ContextPrecision, ContextRecall, Faithfulness

        from src.services.llm import (
            acquire_llm_candidate,
            cooldown_llm_candidate,
            get_llm,
            get_llm_fallbacks,
            is_provider_failover_error,
            release_llm_candidate,
        )
    except ImportError as exc:
        return RagasOutcome(
            topic_id=sample.topic_id,
            error=(
                "không nạp được RAGAS hoặc LLM client; cài dependencies rồi chạy trong worker: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    def evaluator_for(candidate: Any):
        endpoint = candidate.endpoint
        # Gemini exposes an OpenAI-compatible endpoint, which lets RAGAS 0.4
        # use its required InstructorLLM without changing the provider.
        host = (
            "https://generativelanguage.googleapis.com/v1beta/openai"
            if endpoint.provider == "google"
            else endpoint.host or "https://api.openai.com"
        )
        base_url = host.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        return llm_factory(
            endpoint.model,
            provider="openai",
            client=AsyncOpenAI(api_key=endpoint.api_key, base_url=base_url),
            max_tokens=8192,
        )

    scorers: list[tuple[str, Any, dict[str, Any]]] = [
        (
            "faithfulness",
            Faithfulness,
            {
                "user_input": sample.user_input,
                "response": sample.response,
                "retrieved_contexts": sample.retrieved_contexts,
            },
        ),
    ]
    if sample.reference:
        reference_inputs = {
            "user_input": sample.user_input,
            "reference": sample.reference,
            "retrieved_contexts": sample.retrieved_contexts,
        }
        scorers += [
            ("context_precision", ContextPrecision, reference_inputs),
            ("context_recall", ContextRecall, reference_inputs),
        ]

    outcome = RagasOutcome(topic_id=sample.topic_id)
    candidates = [get_llm(), *get_llm_fallbacks()]
    preferred_index = 0
    for name, metric_type, inputs in scorers:
        last_error: Exception | None = None
        attempted: list[Any] = []
        for offset in range(len(candidates)):
            remaining = [item for item in candidates if all(item is not tried for tried in attempted)]
            if not remaining:
                break
            candidate = await acquire_llm_candidate(remaining)
            attempted.append(candidate)
            index = next(i for i, item in enumerate(candidates) if item is candidate)
            succeeded = False
            try:
                result = await metric_type(llm=evaluator_for(candidate)).ascore(**inputs)
                value = float(result.value)
                if not 0.0 <= value <= 1.0:
                    raise ValueError(f"RAGAS trả score ngoài [0, 1]: {value}")
                outcome.scores[name] = value
                succeeded = True
                preferred_index = index
                reason = getattr(result, "reason", None)
                if reason:
                    outcome.reasons[name] = str(reason)
                break
            except Exception as exc:
                last_error = exc
                if is_provider_failover_error(exc):
                    cooldown_llm_candidate(candidate, exc)
                    await asyncio.sleep(2.0)
                if not is_provider_failover_error(exc):
                    break
            finally:
                release_llm_candidate(candidate, succeeded=succeeded)
        if name not in outcome.scores and last_error is not None:
            outcome.reasons[name] = f"giám khảo lỗi: {type(last_error).__name__}: {last_error}"[:500]
        await asyncio.sleep(2.0)
    return outcome


async def score_artifacts(
    runs: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    scorer: RagasScorer = default_scorer,
    gold: dict[str, GoldTopic] | None = None,
    concurrency: int = 1,
) -> list[RagasOutcome]:
    """Score saved artifacts with bounded evaluator concurrency."""
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    semaphore = asyncio.Semaphore(concurrency)

    async def score_one(record: dict[str, Any], artifact: dict[str, Any]) -> RagasOutcome | None:
        if record.get("outcome") != "completed":
            return None
        sample, error = sample_from_artifact(
            record, artifact, gold=(gold or {}).get(str(record.get("topic_id") or "")),
        )
        if sample is None:
            return RagasOutcome(topic_id=str(record.get("topic_id") or "unknown"), error=error)
        async with semaphore:
            try:
                return await scorer(sample)
            except Exception as exc:
                return RagasOutcome(
                    topic_id=sample.topic_id,
                    error=f"giám khảo lỗi: {type(exc).__name__}: {exc}"[:500],
                )

    outcomes = await asyncio.gather(
        *(score_one(record, artifact) for record, artifact in zip(runs, artifacts, strict=True))
    )
    return [outcome for outcome in outcomes if outcome is not None]


def aggregate(outcomes: list[RagasOutcome]) -> dict[str, MetricResult]:
    """Aggregate each RAGAS metric while preserving unjudged reasons."""
    aggregated: dict[str, MetricResult] = {}
    for key, label in _LABELS.items():
        measured = [(outcome, outcome.scores[key]) for outcome in outcomes if key in outcome.scores]
        unavailable = [
            f"{outcome.topic_id}: {outcome.reasons.get(key) or outcome.error or 'không có reference_answer'}"
            for outcome in outcomes
            if key not in outcome.scores
        ]
        if not measured:
            aggregated[key] = MetricResult(
                name=label,
                value=None,
                unit="ratio",
                unmeasured_reason=(
                    "; ".join(unavailable[:5])
                    or "không có artifact hoàn tất nào đủ dữ liệu để chấm"
                ),
            )
            continue
        failures = [
            {
                "topic_id": outcome.topic_id,
                "score": score,
                "reason": outcome.reasons.get(key, "dưới ngưỡng"),
            }
            for outcome, score in measured
            if score < RAGAS_TARGETS[key]
        ]
        aggregated[key] = MetricResult(
            name=label,
            value=sum(score for _, score in measured) / len(measured),
            unit="ratio",
            detail=(
                f"Trung bình {len(measured)}/{len(outcomes)} artifact được chấm. "
                f"Mục tiêu nội bộ: ≥{RAGAS_TARGETS[key]:.0%}. "
                "Đây là LLM-as-judge, chỉ dùng theo dõi regression; không thay kiểm chứng citation tất định."
            ),
            failures=failures,
        )
    return aggregated


def review_traceability_metrics(
    runs: list[dict[str, Any]], artifacts: list[dict[str, Any]],
) -> dict[str, MetricResult]:
    """Pool deterministic final-review -> paper -> quote links.

    This answers whether final prose has auditable paper citations and whether
    those papers connect to an extracted quote. Faithfulness below asks the
    separate semantic question: is that prose supported by those quotes?
    """
    grouped: dict[str, list[MetricResult]] = {}
    for record, artifact in zip(runs, artifacts, strict=True):
        if record.get("kind") == "negative_control" or record.get("outcome") != "completed":
            continue
        result = artifact.get("result") or {}
        for metric in (trust.review_citation_validity(result), trust.review_evidence_coverage(result)):
            grouped.setdefault(metric.name, []).append(metric)

    pooled: dict[str, MetricResult] = {}
    for name, items in grouped.items():
        measured = [item for item in items if item.measured]
        if not measured:
            reasons = sorted({item.unmeasured_reason for item in items if item.unmeasured_reason})
            pooled[name] = MetricResult(
                name=name, value=None, unit="ratio",
                unmeasured_reason="; ".join(reasons) or "không có review hoàn tất để kiểm",
            )
            continue
        numerator = sum(item.numerator or 0 for item in measured)
        denominator = sum(item.denominator or 0 for item in measured)
        pooled[name] = MetricResult(
            name=name,
            value=numerator / denominator if denominator else None,
            unit="ratio",
            numerator=numerator,
            denominator=denominator,
            detail=(measured[0].detail + f" (Gộp {len(measured)} literature review.)").strip(),
            failures=[failure for item in measured for failure in item.failures],
            unmeasured_reason=None if denominator else "không có citation/đoạn review để gộp",
        )
    return pooled


def render_markdown(
    run_dir: Path,
    outcomes: list[RagasOutcome],
    metrics: dict[str, MetricResult],
    *,
    paper_outcomes: list[PaperGoldOutcome] | None = None,
    paper_metrics: dict[str, MetricResult] | None = None,
    review_metrics: dict[str, MetricResult] | None = None,
    source_metric: MetricResult | None = None,
) -> str:
    """Render a standalone, audit-oriented literature-source report."""
    lines = [
        "# Literature-source evaluation — RAGAS evidence grounding",
        "",
        "> Câu hỏi đo: **Hệ thống có lấy paper thật, liên quan chủ đề, và dùng evidence từ paper đó để viết literature review không?**",
        "",
        "> RAGAS là LLM-as-judge cho phần evidence → review. Nó chỉ để so sánh các phiên bản cùng judge/model; "
        "không thay thế kiểm tra citation/evidence tất định hoặc gold do người duyệt.",
        "",
        f"> Artifact thô: `{run_dir}` · {sum(outcome.judged for outcome in outcomes)}/{len(outcomes)} lượt có score.",
        "",
        "## 1. Paper có tồn tại thật?",
        "",
    ]
    if source_metric is None:
        lines.append("- **Chưa đo** — chạy `python -m benchmarks verify-sources RUN_DIR` để tra lại paper ở OpenAlex / Semantic Scholar / arXiv.")
    else:
        lines += [
            f"- **{source_metric.name}**: {source_metric.format_value()}",
            f"- Cách đo: {source_metric.detail or source_metric.unmeasured_reason or '—'}",
        ]

    lines += [
        "",
        "## 2. Paper có liên quan chủ đề?",
        "",
    ]
    if paper_metrics:
        lines += [
            "| Chỉ số | Kết quả |",
            "|---|---|",
            *[f"| {metric.name} | **{metric.format_value()}** |" for metric in paper_metrics.values()],
            "",
        ]
        for metric in paper_metrics.values():
            if not metric.measured:
                lines.append(f"- **{metric.name}**: {metric.unmeasured_reason}")
    else:
        lines.append("- **Chưa đo** — cần gold paper-level do người duyệt freeze.")
    if paper_outcomes:
        unjudged_paper = [outcome for outcome in paper_outcomes if not outcome.judged]
        if unjudged_paper:
            lines.extend(f"- `{outcome.topic_id}` — {outcome.reason}" for outcome in unjudged_paper)
    lines += [
        "",
        "Paper relevance so sánh `result.papers` cuối với paper IDs do reviewer chọn/sửa. "
        "Đây không phải Precision@K/Recall@K theo raw retrieval chunk.",
        "",
        "## 3. Evidence từ paper có đi vào literature review?",
        "",
    ]
    if review_metrics:
        lines += [
            "| Kiểm tra tất định | Kết quả |",
            "|---|---|",
            *[f"| {metric.name} | **{metric.format_value()}** |" for metric in review_metrics.values()],
            "",
        ]
        for metric in review_metrics.values():
            if not metric.measured:
                lines.append(f"- **{metric.name}**: {metric.unmeasured_reason}")
    else:
        lines.append("- **Chưa đo** — artifact không có literature review hoàn tất.")
    lines += [
        "`Citation review trỏ tới paper đã lấy` kiểm citation trong prose cuối; `Đoạn review có evidence truy vết được` "
        "đòi hỏi citation đó nối tới quote của claim hợp lệ. Hai số này kiểm đường dẫn, chưa tự chứng minh câu văn suy ra đúng.",
        "",
        "## 4. RAGAS: evidence có support nội dung review?",
        "",
        "| Chỉ số | Kết quả | Mục tiêu |",
        "|---|---|---|",
    ]
    for key, metric in metrics.items():
        lines.append(f"| {metric.name} | **{metric.format_value()}** | ≥{RAGAS_TARGETS[key]:.0%} |")

    unjudged = [outcome for outcome in outcomes if not outcome.judged]
    if unjudged:
        lines += ["", "## Lượt chưa chấm được", ""]
        lines.extend(f"- `{outcome.topic_id}` — {outcome.error or 'không rõ lý do'}" for outcome in unjudged)

    lines += ["", "### Điểm từng lượt", "", "| Topic | Faithfulness | Context precision | Context recall |", "|---|---:|---:|---:|"]
    for outcome in outcomes:
        lines.append(
            "| `{}` | {} | {} | {} |".format(
                outcome.topic_id,
                _format_score(outcome.scores.get("faithfulness")),
                _format_score(outcome.scores.get("context_precision")),
                _format_score(outcome.scores.get("context_recall")),
            )
        )
    lines += [
        "## Phạm vi đo",
        "",
        "- Faithfulness so sánh **chỉ literature review cuối** với evidence quote của các claim hợp lệ.",
        "- Context Precision/Recall chỉ chạy khi gold đã review có `reference_answer` do người viết; chúng mô tả tập evidence cuối.",
        "- Run mới lưu `retrieval_traces` (top-K chunk, rank, score, provenance). Chỉ khi có gold chunk do reviewer duyệt mới được dùng chúng để chấm Precision@K/Recall@K/MRR/NDCG; report này không tự suy ra gold từ ranking của hệ thống.",
    ]
    return "\n".join(lines)


def _format_score(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "—"
