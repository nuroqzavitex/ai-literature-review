"""Freeze the retrieved-paper corpus already present in benchmark artifacts.

This module deliberately does not fetch PDFs: a benchmark must not silently
copy potentially restricted content. It snapshots the provider metadata,
abstract and retrieval rank that the live pipeline actually returned, so a
reviewer can later download eligible full text and attach gold labels without
changing the baseline run.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_PAPER_FIELDS = (
    "paper_id", "title", "authors", "year", "doi", "url", "abstract",
    "is_open_access", "pdf_url", "relevance_score", "rank",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dataset_provenance(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a stable fingerprint for the exact dataset entries a run used."""
    normalized = [dict(entry) for entry in entries]
    return {
        "entry_count": len(normalized),
        "sha256": hashlib.sha256(_canonical(normalized).encode("utf-8")).hexdigest(),
        "topic_ids": [str(entry.get("topic_id") or "") for entry in normalized],
    }


def _paper_snapshot(paper: dict[str, Any]) -> dict[str, Any] | None:
    paper_id = str(paper.get("paper_id") or "").strip()
    if not paper_id:
        return None
    snap = {field: paper.get(field) for field in _PAPER_FIELDS if paper.get(field) is not None}
    snap["paper_id"] = paper_id
    snap["content_sha256"] = hashlib.sha256(_canonical(snap).encode("utf-8")).hexdigest()
    return snap


def _dataset_entries_from_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recover the original dataset once when a run contains repeated attempts."""
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in runs:
        entry = dict(record.get("dataset_entry") or {})
        key = _canonical(entry)
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries


def build_corpus_snapshot(
    runs: list[dict[str, Any]], artifacts: list[dict[str, Any]], *, source_run: str,
) -> dict[str, Any]:
    """Build an audit-friendly corpus snapshot from completed run artifacts."""
    if len(runs) != len(artifacts):
        raise ValueError("runs và artifacts phải có cùng số phần tử")

    topics: list[dict[str, Any]] = []
    unique_ids: set[str] = set()
    total_papers = 0
    for record, artifact in zip(runs, artifacts, strict=True):
        if record.get("kind") == "negative_control":
            continue
        result = artifact.get("result") or {}
        papers = [
            snapshot for paper in result.get("papers") or []
            if isinstance(paper, dict)
            if (snapshot := _paper_snapshot(paper)) is not None
        ]
        total_papers += len(papers)
        unique_ids.update(paper["paper_id"] for paper in papers)
        topics.append({
            "topic_id": str(record.get("topic_id") or ""),
            "topic": str(record.get("topic") or ""),
            "attempt": int(record.get("attempt") or 0),
            "outcome": str(record.get("outcome") or ""),
            "papers": papers,
        })

    dataset = _dataset_entries_from_runs(runs)
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source_run": source_run,
        "dataset": dataset_provenance(dataset),
        "summary": {
            "topics": len(topics),
            "topics_with_papers": sum(1 for topic in topics if topic["papers"]),
            "papers_total": total_papers,
            "papers_unique": len(unique_ids),
        },
        "topics": topics,
    }


def write_corpus_snapshot(
    run_dir: Path, runs: list[dict[str, Any]], artifacts: list[dict[str, Any]],
) -> tuple[Path, dict[str, Any]]:
    """Persist a corpus snapshot next to the run's immutable raw artifacts."""
    snapshot = build_corpus_snapshot(runs, artifacts, source_run=run_dir.name)
    path = run_dir / "corpus_snapshot.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, snapshot
