"""Coverage metrics — did the review actually cover the topic?

Trust metrics ask "is this true?". Coverage asks "is this enough?". A system
can score perfectly on grounding by returning one safe, well-cited sentence,
so coverage is what stops the trust metrics from being gamed by timidity.
"""

from __future__ import annotations

import re
from typing import Any

from benchmarks.metrics.base import MetricResult, ratio

_WORD = re.compile(r"[a-z0-9]+")
# Words too generic to prove a theme was covered: matching on them alone would
# mark almost any output as a hit.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "for", "in", "on", "to", "with", "using",
    "based", "via", "models", "model", "method", "methods", "approach", "approaches",
    "learning", "network", "networks", "prediction", "analysis", "study", "research",
})


def _content_tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(str(text or "").casefold()) if w not in _STOPWORDS and len(w) > 2}


def theme_recall(result: dict[str, Any], expected_themes: list[str]) -> MetricResult:
    """Share of expected themes that appear in the generated output.

    Matching is token-overlap based, not exact string equality: an expected
    theme counts as covered when at least half of its content words appear in
    one piece of generated output — the literature review, a theme title, or a
    claim. This is deliberately generous — the metric is meant to catch a
    review that *missed a subject area entirely*, not to grade phrasing.

    Only *generated* text counts. Retrieved papers and references are excluded
    on purpose: fetching a paper about a subject is not the same as covering
    it, and counting the corpus would let retrieval alone score the review.
    """
    if not expected_themes:
        return MetricResult(
            name="Độ phủ chủ đề (theme recall)", value=None, unit="ratio",
            unmeasured_reason="dataset không khai báo expected_themes",
        )

    claims_by_id = {str(c.get("claim_id")): c for c in result.get("claims") or []}
    generated: list[str] = []

    # The literature review is the artefact the user actually reads, and it is
    # present even when `themes` is empty — which is the common case. Reading
    # only `themes` made a review that covered its subject look like a miss.
    review = result.get("literature_review") or {}
    if review:
        generated.append(" ".join([
            str(review.get("title", "")),
            str(review.get("abstract", "")),
            str(review.get("introduction", "")),
            " ".join(
                f"{section.get('title', '')} " + " ".join(section.get("paragraphs") or [])
                for section in review.get("sections") or []
            ),
            str(review.get("conclusion", "")),
            str(review.get("limitations", "")),
        ]))

    for theme in result.get("themes") or []:
        text = str(theme.get("title", ""))
        claim = claims_by_id.get(str(theme.get("summary_claim_id")))
        if claim:
            text += " " + str(claim.get("text", ""))
        generated.append(text)

    # Claims count too, always — not only as a fallback. They are part of what
    # the user is shown, and a subject raised in the claims but absent from the
    # review prose was not *missed*, which is what this metric measures.
    generated.extend(str(c.get("text", "")) for c in result.get("claims") or [])

    generated_tokens = [_content_tokens(text) for text in generated]
    covered = 0
    failures: list[dict[str, Any]] = []
    for expected in expected_themes:
        wanted = _content_tokens(expected)
        if not wanted:
            continue
        hit = any(
            len(wanted & tokens) / len(wanted) >= 0.5
            for tokens in generated_tokens
        )
        if hit:
            covered += 1
        else:
            failures.append({"expected_theme": expected, "reason": "không xuất hiện trong theme/claim nào"})

    return ratio(
        "Độ phủ chủ đề (theme recall)",
        numerator=covered,
        denominator=len(expected_themes),
        detail=(
            "Tỷ lệ chủ đề con mà chuyên gia kỳ vọng phải có, và hệ thống thực sự nhắc tới. "
            "⚠️ Dùng token-overlap (≥50% từ khoá xuất hiện trong output): tốt để bắt regression "
            "(hệ thống bỏ sót hẳn một mảng), nhưng KHÔNG đủ để kết luận độ phủ ngữ nghĩa — "
            "cần gold labels của chuyên gia cho mục đích đó."
        ),
        failures=failures,
    )


def fulltext_evidence_ratio(result: dict[str, Any]) -> MetricResult:
    """Share of evidence drawn from full text rather than abstracts.

    Abstract-only evidence is cheap and shallow; full-text evidence is what
    separates this from a search engine with a summarizer bolted on.
    """
    levels = [
        str(item.get("source_level") or "abstract")
        for claim in result.get("claims") or []
        for item in claim.get("evidence") or []
        if str(item.get("quote") or "").strip()
    ]
    full = sum(1 for level in levels if level == "full_text")
    return ratio(
        "Bằng chứng từ full text",
        numerator=full,
        denominator=len(levels),
        detail="Tỷ lệ trích dẫn lấy từ toàn văn thay vì chỉ abstract.",
        empty_reason="không có trích dẫn nào",
    )


def paper_ingestion_metrics(result: dict[str, Any]) -> list[MetricResult]:
    """Classify paper-level full-text availability from persisted P0 metadata.

    Availability and ingestion outcome are separate dimensions in the runtime
    contract.  Count only the three valid combinations so malformed metadata
    cannot silently inflate any availability bucket.  Historical artifacts
    without ingestion metadata remain unmeasured instead of being guessed as
    abstract-only.
    """
    papers = result.get("papers") or []
    categories: list[str | None] = []
    failures: list[dict[str, Any]] = []
    for paper in papers:
        ingestion = paper.get("ingestion") if isinstance(paper, dict) else None
        availability = ingestion.get("content_availability") if isinstance(ingestion, dict) else None
        status = ingestion.get("ingestion_status") if isinstance(ingestion, dict) else None
        source = ingestion.get("full_text_source") if isinstance(ingestion, dict) else None
        url = ingestion.get("full_text_url") if isinstance(ingestion, dict) else None
        chunks = ingestion.get("full_text_chunks") if isinstance(ingestion, dict) else None
        warning = ingestion.get("ingestion_warning") if isinstance(ingestion, dict) else None
        full_text_valid = (
            availability == "full_text"
            and status == "succeeded"
            and source in {"pdf", "pmc_xml", "html"}
            and bool(url)
            and isinstance(chunks, int)
            and chunks > 0
            and not warning
        )
        abstract_valid = (
            availability == "abstract_only"
            and status in {"unavailable", "failed"}
            and source is None
            and url is None
            and chunks == 0
            and bool(warning)
        )
        category = (
            "full_text" if full_text_valid
            else "abstract_unavailable" if abstract_valid and status == "unavailable"
            else "ingestion_failed" if abstract_valid and status == "failed"
            else None
        )
        categories.append(category)
        if category is None:
            failures.append({
                "paper_id": paper.get("paper_id") if isinstance(paper, dict) else None,
                "reason": "thiếu hoặc sai metadata ingestion",
                "content_availability": availability,
                "ingestion_status": status,
            })

    classified = sum(category is not None for category in categories)
    if not papers or classified == 0:
        reason = "artifact không có metadata ingestion P0"
        completeness = MetricResult(
            name="Đủ metadata ingestion cho paper", value=None, unit="ratio",
            numerator=classified, denominator=len(papers), failures=failures,
            detail="Tỷ lệ paper có tuple availability/status hợp lệ.",
            unmeasured_reason=reason,
        )
    else:
        completeness = ratio(
            "Đủ metadata ingestion cho paper",
            numerator=classified,
            denominator=len(papers),
            detail="Tỷ lệ paper có tuple availability/status hợp lệ.",
            failures=failures,
        )

    def category_ratio(name: str, category: str, detail: str) -> MetricResult:
        if classified == 0:
            return MetricResult(
                name=name, value=None, unit="ratio", numerator=0, denominator=0,
                detail=detail, unmeasured_reason="artifact không có metadata ingestion P0",
            )
        return ratio(
            name,
            numerator=sum(value == category for value in categories),
            denominator=classified,
            detail=detail,
        )

    return [
        completeness,
        category_ratio(
            "Paper có full text", "full_text",
            "Tỷ lệ paper đã phân loại tải và parse thành công PDF, PMC XML hoặc HTML toàn văn.",
        ),
        category_ratio(
            "Paper chỉ có abstract (không khả dụng)", "abstract_unavailable",
            "Tỷ lệ paper không tìm thấy nguồn full text và phải dùng abstract.",
        ),
        category_ratio(
            "Paper fallback do lỗi ingestion", "ingestion_failed",
            "Tỷ lệ paper có thử lấy full text nhưng tải hoặc parse thất bại, sau đó fallback abstract.",
        ),
    ]


def corpus_yield(result: dict[str, Any], *, requested: int) -> MetricResult:
    """Papers actually delivered versus the number the user asked for."""
    delivered = len(result.get("papers") or [])
    return ratio(
        "Đạt số bài yêu cầu",
        numerator=min(delivered, requested),
        denominator=requested,
        detail="Tỷ lệ bài giao so với số bài người dùng yêu cầu (max_results trong dataset).",
        failures=[] if delivered >= requested else [{
            "reason": f"thiếu {requested - delivered} bài so với yêu cầu",
        }],
        empty_reason="dataset không khai báo max_results",
    )


def citation_reuse(result: dict[str, Any]) -> MetricResult:
    """Share of retrieved papers that the review actually cites.

    A pipeline that fetches 20 papers and cites 3 is paying for 17 it never
    used — visible directly in cost per useful output.
    """
    corpus = {str(p.get("paper_id")) for p in result.get("papers") or []}
    cited = {
        str(item.get("paper_id"))
        for claim in result.get("claims") or []
        for item in claim.get("evidence") or []
    } | {
        str(paper_id)
        for claim in result.get("claims") or []
        for paper_id in claim.get("supporting_paper_ids") or []
    }
    used = len(corpus & cited)
    return ratio(
        "Bài báo được dùng thật",
        numerator=used,
        denominator=len(corpus),
        detail="Tỷ lệ bài đã tải/xử lý mà thực sự được trích dẫn trong báo cáo.",
        empty_reason="không có bài nào trong corpus",
    )


def pipeline_attrition(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-stage received/emitted/dropped, when the run recorded a ledger.

    Not a MetricResult: this is the audit trail a reader opens after a headline
    number looks wrong, showing exactly which stage discarded the data.
    """
    ledger = status.get("ledger") or status.get("_ledger") or []
    rows: list[dict[str, Any]] = []
    for entry in ledger:
        received = entry.get("received")
        emitted = entry.get("emitted")
        rows.append({
            "stage": entry.get("stage"),
            "received": received,
            "emitted": emitted,
            "dropped": entry.get("dropped") or {},
            "loss_rate": (
                None if not received else round(1 - (emitted or 0) / received, 4)
            ),
        })
    return rows
