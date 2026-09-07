"""Human-reviewed, paper-level relevance gold for literature evaluation.

This evaluates whether the final papers selected for a topic are relevant.
It is intentionally not a passage-level retriever benchmark: the live API
does not expose its ranked candidate chunks, and a system baseline must never
silently certify its own selections as ground truth.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.metrics.base import MetricResult, ratio


_AUTO_LABEL_STOP_WORDS = {
    "about", "after", "among", "analysis", "and", "are", "authors", "both",
    "context", "current", "developed", "does", "for", "from", "have", "into",
    "method", "methods", "model", "models", "paper", "prediction", "results",
    "that", "the", "their", "these", "this", "using", "were", "with",
}
_CHUNK_GRADES = {"irrelevant": 0, "partially_relevant": 1, "relevant": 2}


@dataclass(frozen=True)
class GoldTopic:
    """One human-reviewed paper-level gold entry."""

    topic_id: str
    paper_ids: tuple[str, ...]
    reference_answer: str | None
    paper_metadata: tuple[dict[str, str], ...] = ()
    # A positive-only relevant list can measure whether expected papers were
    # found (recall/hit rate), but cannot declare every other returned paper
    # irrelevant.  Precision is reported only after an exhaustive judgement.
    precision_judged: bool = True


@dataclass(frozen=True)
class PaperGoldOutcome:
    """Deterministic comparison of one returned paper set with frozen gold."""

    topic_id: str
    returned_paper_ids: tuple[str, ...]
    gold_paper_ids: tuple[str, ...]
    matched_paper_ids: tuple[str, ...]
    reason: str | None = None
    matched_gold_paper_ids: tuple[str, ...] = ()
    precision_judged: bool = True

    @property
    def judged(self) -> bool:
        return self.reason is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "returned_paper_ids": list(self.returned_paper_ids),
            "gold_paper_ids": list(self.gold_paper_ids),
            "matched_paper_ids": list(self.matched_paper_ids),
            "matched_gold_paper_ids": list(self.matched_gold_paper_ids),
            "precision_judged": self.precision_judged,
            "reason": self.reason,
        }


def _paper_ids(papers: list[Any] | None) -> tuple[str, ...]:
    """Keep returned order, but do not let duplicate IDs inflate a score."""
    ids: list[str] = []
    for paper in papers or []:
        raw = paper.get("paper_id") if isinstance(paper, dict) else paper
        paper_id = str(raw or "").strip()
        if paper_id:
            ids.append(paper_id)
    return tuple(dict.fromkeys(ids))


def _normalize_arxiv_id(paper_id: str) -> str:
    """Strip version suffix from arXiv IDs for gold comparison.

    System artifacts store versioned IDs (e.g. ``arxiv:2012.01981v3``);
    independent gold typically omits the version.  Stripping the suffix
    allows matching without requiring the curator to track exact versions.
    Non-arXiv IDs (OpenAlex ``W...``, Semantic Scholar ``s2:...``) are
    returned unchanged.
    """
    normalized = paper_id.strip()
    if normalized.lower().startswith("arxiv:"):
        return re.sub(r"v\d+$", "", normalized, flags=re.IGNORECASE).lower()
    if re.fullmatch(r"W\d+", normalized, flags=re.IGNORECASE):
        return f"openalex:{normalized.upper()}"
    if normalized.lower().startswith("openalex:"):
        return f"openalex:{normalized.split(':', 1)[1].upper()}"
    return normalized.casefold()


def _normalize_text(value: str) -> str:
    """Normalize an exact title/DOI alias without making fuzzy relevance calls."""
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _arxiv_aliases(paper: dict[str, Any]) -> tuple[str, ...]:
    """Extract stable arXiv aliases from IDs, DOI values, and URLs."""
    values = [
        str(paper.get("paper_id") or ""),
        str(paper.get("doi") or ""),
        str(paper.get("url") or ""),
    ]
    aliases: list[str] = []
    for value in values:
        match = re.search(r"(?:arxiv[:./]|abs/)([0-9]{4}\.[0-9]{4,5})(?:v\d+)?", value, re.IGNORECASE)
        if match:
            aliases.append(f"arxiv:{match.group(1).lower()}")
    return tuple(dict.fromkeys(aliases))


def _metadata_match_keys(paper: dict[str, Any]) -> tuple[str, ...]:
    """Stable identity aliases supplied by independent metadata, not an LLM."""
    keys: list[str] = []
    paper_id = str(paper.get("paper_id") or "").strip()
    if paper_id:
        keys.append(f"id:{_normalize_arxiv_id(paper_id)}")
    doi_value = str(paper.get("doi") or "").strip()
    doi_value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi_value, flags=re.IGNORECASE)
    doi = _normalize_text(doi_value)
    if doi:
        keys.append(f"doi:{doi}")
    keys.extend(f"id:{alias}" for alias in _arxiv_aliases(paper))
    title = _normalize_text(str(paper.get("title") or ""))
    if title:
        keys.append(f"title:{title}")
    return tuple(keys)


def build_candidate_gold(
    runs: list[dict[str, Any]], artifacts: list[dict[str, Any]], *, source_run: str,
) -> dict[str, Any]:
    """Seed a reviewable gold file from the first completed positive attempt.

    The output is deliberately marked ``reviewed: false``.  A baseline system
    must never silently certify its own selections as gold; a reviewer has to
    remove irrelevant IDs, add any known important IDs, write a reference
    answer, then set ``reviewed`` to true.
    """
    if len(runs) != len(artifacts):
        raise ValueError("runs và artifacts phải có cùng số phần tử")

    topics: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record, artifact in zip(runs, artifacts, strict=True):
        if record.get("kind") == "negative_control" or record.get("outcome") != "completed":
            continue
        topic_id = str(record.get("topic_id") or "").strip()
        if not topic_id or topic_id in seen:
            continue
        paper_ids = _paper_ids((artifact.get("result") or {}).get("papers") or [])
        if not paper_ids:
            continue
        seen.add(topic_id)
        topics.append({
            "topic_id": topic_id,
            "topic": str(record.get("topic") or ""),
            "paper_ids": list(paper_ids),
            "reference_answer": "",
            "reviewed": False,
            "review_note": (
                "Reviewer: bỏ paper không liên quan, thêm paper liên quan bị bỏ sót, "
                "viết reference_answer rồi đặt reviewed=true."
            ),
        })

    return {
        "schema_version": 1,
        "scope": "paper_level_relevance",
        "source_run": source_run,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "topics": topics,
    }


def write_candidate_gold(
    target: Path, runs: list[dict[str, Any]], artifacts: list[dict[str, Any]], *, source_run: str,
) -> dict[str, Any]:
    """Create a candidate gold file once; refuse to overwrite frozen review work."""
    if target.exists():
        raise FileExistsError(f"Gold đã tồn tại: {target}. Không ghi đè gold đã review.")
    candidate = build_candidate_gold(runs, artifacts, source_run=source_run)
    target.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    return candidate


def build_chunk_candidate_gold(
    runs: list[dict[str, Any]], artifacts: list[dict[str, Any]], *, source_run: str,
) -> dict[str, Any]:
    """Seed reviewable chunk labels from persisted retrieval traces.

    ``suggested_label`` is only a triage hint: a chunk selected by the live
    grounding filter is marked ``likely_relevant``; every other retrieved
    chunk stays ``review_required``.  No system ranking becomes gold without a
    reviewer changing labels and setting ``reviewed``.
    """
    topics: list[dict[str, Any]] = []
    for record, artifact in zip(runs, artifacts, strict=True):
        if record.get("kind") == "negative_control" or record.get("outcome") != "completed":
            continue
        traces = (artifact.get("result") or {}).get("retrieval_traces") or []
        if not traces:
            continue
        reviewable = []
        for trace in traces:
            selected = set(trace.get("selected_document_ids") or [])
            chunks = []
            for chunk in trace.get("ranked_chunks") or []:
                document_id = str(chunk.get("document_id") or "").strip()
                if not document_id:
                    continue
                chunks.append({
                    "document_id": document_id,
                    "paper_id": str(chunk.get("paper_id") or ""),
                    "content_hash": chunk.get("content_hash"),
                    "rank": chunk.get("rank"),
                    "retrieval_score": chunk.get("retrieval_score"),
                    "quote": str(chunk.get("quote") or ""),
                    "suggested_label": "likely_relevant" if document_id in selected else "review_required",
                    "reviewer_label": None,
                })
            if chunks:
                reviewable.append({
                    "stage": trace.get("stage"),
                    "query": trace.get("query"),
                    "paper_filter": trace.get("paper_filter") or [],
                    "chunks": chunks,
                })
        if reviewable:
            topics.append({
                "topic_id": record.get("topic_id"),
                "topic": record.get("topic"),
                "reviewed": False,
                "review_note": "Duyệt reviewer_label: relevant / partially_relevant / irrelevant; thêm gold chunk bị bỏ sót nếu có.",
                "traces": reviewable,
            })
    return {
        "schema_version": 1,
        "scope": "chunk_level_relevance_candidate",
        "source_run": source_run,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "topics": topics,
    }


def write_chunk_candidate_gold(
    target: Path, runs: list[dict[str, Any]], artifacts: list[dict[str, Any]], *, source_run: str,
) -> dict[str, Any]:
    if target.exists():
        raise FileExistsError(f"Chunk gold đã tồn tại: {target}. Không ghi đè gold đang review.")
    candidate = build_chunk_candidate_gold(runs, artifacts, source_run=source_run)
    if not candidate["topics"]:
        raise ValueError("Run chưa có retrieval_traces; chạy mới workflow sau khi deploy trace rồi seed lại.")
    target.write_text(json.dumps(candidate, ensure_ascii=False, indent=2), encoding="utf-8")
    return candidate


def _content_terms(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9]{4,}", text.lower())
        if word not in _AUTO_LABEL_STOP_WORDS
    }


def auto_label_chunk_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach reproducible proxy labels; they are explicitly not reviewer gold.

    A chunk is graded from lexical overlap with the retrieval query.  This is
    intentionally conservative and auditable: it makes a useful regression
    proxy without pretending that the system's own retrieval decision is a
    human relevance judgment.
    """
    if payload.get("schema_version") != 1 or payload.get("scope") not in {
        "chunk_level_relevance_candidate", "chunk_level_relevance_auto_labeled",
    }:
        raise ValueError("không phải chunk-gold candidate schema_version=1")

    for topic in payload.get("topics") or []:
        for trace in topic.get("traces") or []:
            query_terms = _content_terms(str(trace.get("query") or ""))
            for chunk in trace.get("chunks") or []:
                overlap = sorted(query_terms & _content_terms(str(chunk.get("quote") or "")))
                if len(overlap) >= 3:
                    label = "relevant"
                elif overlap:
                    label = "partially_relevant"
                else:
                    label = "irrelevant"
                chunk["auto_label"] = label
                chunk["auto_label_reason"] = f"query_term_overlap={len(overlap)}:{','.join(overlap[:8])}"

    payload["scope"] = "chunk_level_relevance_auto_labeled"
    payload["auto_label_policy"] = "lexical_query_overlap_v1"
    payload["auto_labeled_at_utc"] = datetime.now(UTC).isoformat()
    return payload


def write_auto_chunk_labels(target: Path) -> dict[str, Any]:
    """Label a candidate file in place while preserving reviewer labels."""
    payload = json.loads(target.read_text(encoding="utf-8"))
    labeled = auto_label_chunk_candidate(payload)
    target.write_text(json.dumps(labeled, ensure_ascii=False, indent=2), encoding="utf-8")
    return labeled


def score_auto_chunk_retrieval(payload: dict[str, Any]) -> dict[str, MetricResult]:
    """Score ranked traces against explicit proxy labels, never report Recall@K.

    The saved trace contains only returned top-K chunks.  It cannot establish
    how many relevant chunks existed outside that set, so Recall@K remains
    unmeasured until an external/full-corpus gold pool is added.
    """
    if payload.get("scope") != "chunk_level_relevance_auto_labeled":
        raise ValueError("cần chạy auto-label trước khi chấm chunk retrieval")

    traces = [
        trace for topic in payload.get("topics") or []
        for trace in topic.get("traces") or []
        if trace.get("chunks")
    ]
    if not traces:
        return {
            "precision_at_1": MetricResult("Auto-label Precision@1", None, "ratio", unmeasured_reason="không có ranked chunk"),
            "precision_at_3": MetricResult("Auto-label Precision@3", None, "ratio", unmeasured_reason="không có ranked chunk"),
            "precision_at_5": MetricResult("Auto-label Precision@5", None, "ratio", unmeasured_reason="không có ranked chunk"),
            "mrr": MetricResult("Auto-label MRR", None, "ratio", unmeasured_reason="không có ranked chunk"),
            "ndcg_at_5": MetricResult("Auto-label NDCG@5", None, "ratio", unmeasured_reason="không có ranked chunk"),
            "recall_at_5": MetricResult("Recall@5", None, "ratio", unmeasured_reason="trace chỉ giữ top-K; thiếu gold relevant chunk ngoài kết quả trả về"),
        }

    def grade(chunk: dict[str, Any]) -> int:
        label = str(chunk.get("auto_label") or "")
        if label not in _CHUNK_GRADES:
            raise ValueError("mọi chunk phải có auto_label hợp lệ")
        return _CHUNK_GRADES[label]

    ranked = [sorted(trace["chunks"], key=lambda item: int(item.get("rank") or 10**9)) for trace in traces]
    metrics: dict[str, MetricResult] = {}
    for k in (1, 3, 5):
        retrieved = sum(min(k, len(chunks)) for chunks in ranked)
        relevant = sum(sum(grade(chunk) > 0 for chunk in chunks[:k]) for chunks in ranked)
        metrics[f"precision_at_{k}"] = ratio(
            f"Auto-label Precision@{k}", relevant, retrieved,
            detail=(f"Gộp {len(ranked)} retrieval trace; relevant gồm relevant và partially_relevant "
                    "theo lexical_query_overlap_v1, chỉ dùng regression nội bộ."),
        )

    reciprocal_ranks = []
    ndcgs = []
    for chunks in ranked:
        grades = [grade(chunk) for chunk in chunks[:5]]
        first = next((index + 1 for index, value in enumerate(grades) if value > 0), None)
        reciprocal_ranks.append(1 / first if first else 0.0)
        dcg = sum((2 ** value - 1) / math.log2(index + 2) for index, value in enumerate(grades))
        ideal = sorted((grade(chunk) for chunk in chunks), reverse=True)[:5]
        idcg = sum((2 ** value - 1) / math.log2(index + 2) for index, value in enumerate(ideal))
        ndcgs.append(dcg / idcg if idcg else 0.0)
    metrics["mrr"] = MetricResult("Auto-label MRR", sum(reciprocal_ranks) / len(ranked), "ratio",
                                  detail=f"Macro-average trên {len(ranked)} retrieval trace; proxy auto-label.")
    metrics["ndcg_at_5"] = MetricResult("Auto-label NDCG@5", sum(ndcgs) / len(ranked), "ratio",
                                         detail=f"Macro-average trên {len(ranked)} retrieval trace; grade relevant=2, partial=1.")
    metrics["recall_at_5"] = MetricResult(
        "Recall@5", None, "ratio",
        unmeasured_reason="trace chỉ giữ top-K; thiếu gold relevant chunk ngoài kết quả trả về",
    )
    return metrics


def load_gold(path: Path) -> dict[str, GoldTopic]:
    """Load only reviewed entries, rejecting malformed or duplicate topic IDs."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("ragas gold phải có schema_version = 1")
    entries = payload.get("topics")
    if not isinstance(entries, list):
        raise ValueError("ragas gold phải có mảng topics")

    gold: dict[str, GoldTopic] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("reviewed"):
            continue
        topic_id = str(entry.get("topic_id") or "").strip()
        paper_ids = _paper_ids(entry.get("paper_ids") if isinstance(entry.get("paper_ids"), list) else [])
        if not topic_id or not paper_ids:
            raise ValueError("mỗi gold topic đã review phải có topic_id và paper_ids")
        if topic_id in gold:
            raise ValueError(f"gold trùng topic_id: {topic_id}")
        reference = str(entry.get("reference_answer") or "").strip() or None
        metadata_by_id: dict[str, dict[str, str]] = {
            paper_id: {"paper_id": paper_id}
            for paper_id in paper_ids
        }
        for paper in entry.get("paper_relevance") or []:
            if not isinstance(paper, dict):
                continue
            paper_id = str(paper.get("paper_id") or "").strip()
            if paper_id not in metadata_by_id:
                continue
            metadata_by_id[paper_id] = {
                "paper_id": paper_id,
                "title": str(paper.get("title") or ""),
                "doi": str(paper.get("doi") or ""),
            }
        gold[topic_id] = GoldTopic(
            topic_id,
            paper_ids,
            reference,
            tuple(metadata_by_id[paper_id] for paper_id in paper_ids),
            bool(entry.get("precision_judged", False)),
        )
    return gold


def compare_paper_gold(
    runs: list[dict[str, Any]], artifacts: list[dict[str, Any]], gold: dict[str, GoldTopic],
) -> list[PaperGoldOutcome]:
    """Compare final returned papers with reviewed paper-level gold.

    arXiv IDs are normalized (version suffix stripped) before comparison so
    that ``arxiv:2012.01981v3`` in the run artifact matches ``arxiv:2012.01981``
    in an independent gold file created without tracking exact versions.
    This intentionally uses ``result.papers`` rather than pretending those are
    the raw ranked contexts sent to the model.
    """
    outcomes: list[PaperGoldOutcome] = []
    for record, artifact in zip(runs, artifacts, strict=True):
        if record.get("kind") == "negative_control" or record.get("outcome") != "completed":
            continue
        topic_id = str(record.get("topic_id") or "unknown")
        entry = gold.get(topic_id)
        if entry is None:
            outcomes.append(PaperGoldOutcome(topic_id, (), (), (), "không có gold relevance đã review"))
            continue
        returned_papers = (artifact.get("result") or {}).get("papers") or []
        returned = _paper_ids(returned_papers)
        gold_by_key: dict[str, str] = {}
        for paper in entry.paper_metadata or tuple({"paper_id": pid} for pid in entry.paper_ids):
            for key in _metadata_match_keys(paper):
                gold_by_key.setdefault(key, str(paper["paper_id"]))

        matched: list[str] = []
        matched_gold: list[str] = []
        seen_gold: set[str] = set()
        for paper in returned_papers:
            if not isinstance(paper, dict):
                continue
            paper_id = str(paper.get("paper_id") or "").strip()
            if not paper_id:
                continue
            gold_id = next((gold_by_key[key] for key in _metadata_match_keys(paper) if key in gold_by_key), None)
            if gold_id and gold_id not in seen_gold:
                matched.append(paper_id)
                matched_gold.append(gold_id)
                seen_gold.add(gold_id)
        outcomes.append(PaperGoldOutcome(
            topic_id, returned, entry.paper_ids, tuple(matched),
            matched_gold_paper_ids=tuple(matched_gold),
            precision_judged=entry.precision_judged,
        ))
    return outcomes


def aggregate_paper_gold(outcomes: list[PaperGoldOutcome]) -> dict[str, MetricResult]:
    """Pool per-topic ID matches into paper-level precision and recall."""
    judged = [outcome for outcome in outcomes if outcome.judged]
    unavailable = [f"{outcome.topic_id}: {outcome.reason}" for outcome in outcomes if not outcome.judged]
    if not judged:
        reason = "; ".join(unavailable[:5]) or "không có positive run hoàn tất"
        return {
            "paper_precision": MetricResult("Paper relevance precision (gold)", None, "ratio", unmeasured_reason=reason),
            "paper_recall": MetricResult("Paper relevance recall (gold)", None, "ratio", unmeasured_reason=reason),
        }

    matched = sum(len(outcome.matched_paper_ids) for outcome in judged)
    returned = sum(len(outcome.returned_paper_ids) for outcome in judged)
    expected = sum(len(outcome.gold_paper_ids) for outcome in judged)
    failures = [
        {
            "topic_id": outcome.topic_id,
            "missing_gold_paper_ids": [
                paper_id for paper_id in outcome.gold_paper_ids if paper_id not in outcome.matched_gold_paper_ids
            ],
        }
        for outcome in judged
        if len(outcome.matched_gold_paper_ids) != len(outcome.gold_paper_ids)
    ]
    detail = (
        f"Gộp {len(judged)}/{len(outcomes)} positive run có gold đã review. "
        "So sánh final result.papers với paper IDs liên quan do reviewer freeze; "
        "không phải Precision@K/Recall@K theo chunk."
    )
    precision = (
        ratio(
            "Paper relevance precision (gold)", matched, returned,
            detail=detail,
            failures=failures,
            empty_reason="các run có gold không trả paper nào",
        )
        if all(outcome.precision_judged for outcome in judged)
        else MetricResult(
            "Paper relevance precision (gold)", None, "ratio",
            unmeasured_reason=(
                "gold hiện là positive-only: chưa gán nhãn exhaustive cho toàn bộ paper trả về; "
                "chỉ paper recall/hit rate được đo."
            ),
        )
    )
    return {
        "paper_precision": precision,
        "paper_recall": ratio(
            "Paper relevance recall (gold)", matched, expected,
            detail=detail,
            failures=failures,
            empty_reason="gold relevance rỗng",
        ),
    }
