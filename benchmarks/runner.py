"""Run the benchmark dataset against a live API and save raw artifacts.

Separation of concerns on purpose: this module only *produces evidence*
(the untouched JSON the API returned, plus timing), and never computes a
metric. ``report.py`` turns artifacts into numbers. That split means any
number in a report can be recomputed months later from the stored artifact,
and a metric bug never silently rewrites history — you re-run the report, not
the whole expensive pipeline.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from benchmarks.corpus import dataset_provenance

DEFAULT_BASE_URL = "http://localhost:8000/api/v1"
_TERMINAL = {"approved", "completed", "changes_requested", "error", "cancelled"}
_RESULTS_DIR = Path(__file__).parent / "results"


# Error-message substrings that indicate the pipeline *intentionally* refused
# to produce output (e.g., "no relevant papers — refusing to fabricate").
# Infrastructure crashes (OOM, timeout, DB error) will never match these.
# Checked case-insensitively against status["error"].
_INTENTIONAL_REFUSAL_SIGNALS = (
    "no relevant",
    "refuse",
    "insufficient evidence",
    "nothing found",
    "out of scope",
    "không liên quan",
    "không tìm thấy",
    "không có bài báo nào phù hợp",
    "out_of_scope",
)


@dataclass
class RunRecord:
    """One attempt at one topic. Everything a metric might need, plus why it failed."""

    topic_id: str
    topic: str
    kind: str
    attempt: int
    outcome: str = "not_started"
    error: str | None = None
    error_class: str | None = None
    job_id: str | None = None
    latency_seconds: float | None = None
    valid_claims: int | None = None
    papers: int | None = None
    started_at: str = ""
    artifact: str | None = None
    # How the pipeline signalled a non-result on a negative-control topic.
    # "intentional_refusal": API completed cleanly with empty output, or the
    #   error message contains an explicit refusal phrase — the product behaved
    #   correctly.
    # "infrastructure_error": API errored with no refusal keyword — could be
    #   a real crash that happened to produce empty output; should NOT be
    #   counted as a successful negative-control test.
    # None: not a negative-control run, or outcome was not "refused".
    refusal_kind: str | None = None
    dataset_entry: dict[str, Any] = field(default_factory=dict)


async def _poll_until_terminal(
    client: httpx.AsyncClient, base_url: str, job_id: str, *, timeout: float, interval: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while True:
        response = await client.get(f"{base_url}/reviews/{job_id}/status")
        response.raise_for_status()
        last = response.json()
        if str(last.get("status")) in _TERMINAL:
            return last
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"job {job_id} vẫn ở '{last.get('status')}' (node={last.get('current_node')}) sau {timeout:.0f}s"
            )
        await asyncio.sleep(interval)


async def run_one(
    client: httpx.AsyncClient,
    entry: dict[str, Any],
    *,
    base_url: str,
    attempt: int,
    run_dir: Path,
    user_id: str,
    timeout: float,
    poll_interval: float,
) -> RunRecord:
    record = RunRecord(
        topic_id=str(entry.get("topic_id")),
        topic=str(entry.get("topic")),
        kind=str(entry.get("kind", "positive")),
        attempt=attempt,
        started_at=datetime.now(UTC).isoformat(),
        dataset_entry=entry,
    )
    started = time.monotonic()
    try:
        created = await client.post(
            f"{base_url}/reviews",
            json={
                "topic": entry["topic"],
                "max_results": int(entry.get("max_results", 15)),
                "user_id": user_id,
                "role": "researcher",
                # Autonomous mode removes human pauses so the measured latency
                # is the system's, not the operator's reaction time.
                "execution_mode": "autonomous",
            },
        )
        created.raise_for_status()
        record.job_id = str(created.json()["job_id"])

        status = await _poll_until_terminal(
            client, base_url, record.job_id, timeout=timeout, interval=poll_interval,
        )
        record.latency_seconds = time.monotonic() - started

        result: dict[str, Any] = {}
        if str(status.get("status")) in {"approved", "completed", "changes_requested"}:
            fetched = await client.get(f"{base_url}/reviews/{record.job_id}")
            if fetched.status_code == 200:
                result = fetched.json()

        record.papers = len(result.get("papers") or status.get("papers") or [])
        record.valid_claims = len([
            c for c in result.get("claims") or [] if c.get("validation_status") == "valid"
        ])
        errored = str(status.get("status")) in {"error", "cancelled"}
        if errored:
            record.error = str(status.get("error") or "không rõ")
            record.error_class = record.error.split(":")[0][:60]

        # Negative-control scoring — distinguishes *intentional* refusals from
        # infra crashes that happened to produce empty output.
        #
        # Case 1 — completed + empty: the pipeline ran the full graph, reached
        #   out_of_scope or returned cleanly with no papers.  That is the
        #   clearest possible intentional refusal signal.
        # Case 2 — error + refusal keyword: the pipeline crashed *because* it
        #   refused (e.g., raising an exception when it found nothing worth
        #   reporting).  The keyword list is conservative to avoid false
        #   positives on unrelated failures.
        # Case 3 — error + no keyword: could be a DB crash, OOM, or timeout
        #   that also produced empty output by coincidence.  Counting this as
        #   a pass would let a completely broken pipeline score 100% on
        #   negative controls, which is exactly backwards.
        produced_nothing = record.papers == 0 and record.valid_claims == 0
        if record.kind == "negative_control" and produced_nothing:
            error_lower = (record.error or "").lower()
            is_intentional = (
                not errored  # completed cleanly with empty output
                or any(sig in error_lower for sig in _INTENTIONAL_REFUSAL_SIGNALS)
            )
            record.outcome = "refused"
            record.refusal_kind = "intentional_refusal" if is_intentional else "infrastructure_error"
        elif produced_nothing and not errored:
            # A REAL topic the pipeline finished cleanly on but returned nothing
            # for. That is a product failure (or at best an unproven refusal),
            # and must not hide inside a 100% success rate.
            record.outcome = "empty_result"
            record.error = "hệ thống hoàn tất nhưng không trả bài/claim nào cho chủ đề thật"
            record.error_class = "empty_result"
        else:
            record.outcome = "failed" if errored else "completed"

        artifact_path = run_dir / f"{record.topic_id}_attempt{attempt}.json"
        artifact_path.write_text(
            json.dumps({"status": status, "result": result}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        record.artifact = artifact_path.name
    except Exception as exc:
        record.latency_seconds = time.monotonic() - started
        record.outcome = "failed"
        record.error = str(exc)[:500]
        record.error_class = type(exc).__name__
    return record


async def run_benchmark(
    dataset: list[dict[str, Any]],
    *,
    base_url: str = DEFAULT_BASE_URL,
    repeat: int = 1,
    user_id: str = "benchmark_runner",
    timeout: float = 1800.0,
    poll_interval: float = 5.0,
    concurrency: int = 1,
    results_dir: Path | None = None,
    label: str = "",
) -> tuple[Path, list[RunRecord]]:
    """Execute every dataset entry, with bounded concurrent jobs when requested."""
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = (results_dir or _RESULTS_DIR) / (f"{stamp}-{label}" if label else stamp)
    run_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot the run environment before the first API call.  Written
    # atomically so a crash mid-run still leaves a readable env file.
    env = await _collect_run_env(base_url)
    env["dataset"] = dataset_provenance(dataset)
    env_path = run_dir / "run_env.json"
    _write_json_atomically(env_path, env)
    print(f"  💾 Môi trường: commit={env['git_commit'][:8]} dirty={env['git_dirty']} → {env_path.name}", flush=True)

    records_by_index: dict[int, RunRecord] = {}
    total = len(dataset) * repeat
    scheduled = [
        (index, attempt, entry)
        for index, (attempt, entry) in enumerate(
            ((attempt, entry) for attempt in range(1, repeat + 1) for entry in dataset), start=1,
        )
    ]
    semaphore = asyncio.Semaphore(concurrency)
    checkpoint_lock = asyncio.Lock()

    async def execute(index: int, attempt: int, entry: dict[str, Any], client: httpx.AsyncClient) -> RunRecord:
        async with semaphore:
            print(f"[{index}/{total}] {entry['topic_id']} · lần {attempt} · {entry['topic'][:52]}", flush=True)
            record = await run_one(
                client, entry,
                base_url=base_url, attempt=attempt, run_dir=run_dir,
                user_id=user_id, timeout=timeout, poll_interval=poll_interval,
            )
            mark = "✅" if record.outcome in {"completed", "refused"} else "❌"
            latency = f"{record.latency_seconds:.0f}s" if record.latency_seconds else "—"
            outcome_note = (
                " (đúng: từ chối bịa)" if record.outcome == "refused"
                else " (chủ đề thật mà trả rỗng)" if record.outcome == "empty_result"
                else ""
            )
            print(
                f"      {mark} {record.outcome}{outcome_note}"
                + f" · {latency} · {record.papers or 0} bài · {record.valid_claims or 0} claim"
                + (f" · {record.error[:80]}" if record.error else ""), flush=True,
            )
            async with checkpoint_lock:
                records_by_index[index] = record
                _write_runs(run_dir, [records_by_index[key] for key in sorted(records_by_index)])
            return record

    async with httpx.AsyncClient(timeout=60.0) as client:
        await asyncio.gather(*(execute(index, attempt, entry, client) for index, attempt, entry in scheduled))

    records = [records_by_index[index] for index, _, _ in scheduled]
    _write_runs(run_dir, records)
    return run_dir, records


def _write_runs(run_dir: Path, records: list[RunRecord]) -> None:
    """Persist the run log atomically so a crash mid-write cannot corrupt it."""
    _write_json_atomically(run_dir / "runs.json", [asdict(record) for record in records])


def _write_json_atomically(target: Path, payload: Any) -> None:
    """Write JSON via a sibling temporary file then replace the target."""
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    temporary.replace(target)


async def check_api_alive(base_url: str = DEFAULT_BASE_URL) -> tuple[bool, str]:
    """Fail fast with a clear reason rather than a wall of connection errors."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/health")
            if response.status_code == 200:
                return True, "OK"
            return False, f"/health trả HTTP {response.status_code}"
    except Exception as exc:
        return False, f"không kết nối được {base_url}: {type(exc).__name__}: {exc}"


def _git_info() -> dict[str, str | bool]:
    """Best-effort git snapshot — silently degrades when git is unavailable."""
    import subprocess  # noqa: PLC0415 — local import keeps startup fast

    def _run(cmd: list[str]) -> str:
        try:
            return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
        except Exception:
            return ""

    commit = _run(["git", "rev-parse", "HEAD"])
    dirty_output = _run(["git", "status", "--short"])
    return {
        "git_commit": commit or "unknown",
        "git_dirty": bool(dirty_output),
        "git_dirty_files": dirty_output or "",
    }


async def _collect_run_env(base_url: str) -> dict[str, Any]:
    """Snapshot the run environment for traceability.

    Written to run_env.json before the first API call so that a partial run
    (interrupted mid-way) still has enough context to interpret its artifacts.
    Fields:
    - git_commit / git_dirty: what code was running
    - base_url: which API endpoint was targeted
    - health_response: whatever /health returned (includes model/provider info
      if the backend exposes it)
    - timestamp_utc: wall clock at the moment of the snapshot
    """
    env: dict[str, Any] = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "base_url": base_url,
        **_git_info(),
        "health_response": None,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/health")
            env["health_response"] = resp.json() if resp.status_code == 200 else {"http_status": resp.status_code}
    except Exception as exc:
        env["health_response"] = {"error": str(exc)}
    return env
