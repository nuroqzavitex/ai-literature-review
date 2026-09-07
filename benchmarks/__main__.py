"""CLI: `python -m benchmarks <run|report|selftest>`.

``selftest`` exists because a benchmark that has never been tested is just
another untested program, and a wrong metric is more dangerous than no metric:
it produces confident numbers nobody questions. It runs the metric functions
against fixtures with known, deliberately planted defects and asserts each one
is caught — no API, no database, no network.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from benchmarks.corpus import write_corpus_snapshot
from benchmarks.gold import (
    aggregate_paper_gold, compare_paper_gold, load_gold, score_auto_chunk_retrieval,
    write_auto_chunk_labels, write_candidate_gold, write_chunk_candidate_gold,
)
from benchmarks.metrics import trust
from benchmarks.report import compute_metrics, load_run, render_markdown
from benchmarks.runner import DEFAULT_BASE_URL, RunRecord, check_api_alive, run_benchmark

_DATASET = Path(__file__).parent / "datasets" / "topics.json"
_RAGAS_GOLD = Path(__file__).parent / "datasets" / "ragas_gold.json"
_RAGAS_CHUNK_GOLD = Path(__file__).parent / "datasets" / "ragas_chunk_gold.json"
_GOLD_MANIFEST = Path(__file__).parent / "datasets" / "gold_manifest.json"


def _load_reviewed_gold_for_topics(gold_path: Path, topic_ids: set[str]) -> dict:
    """Load one explicitly configured gold file per topic.

    A manifest is preferred over globbing so archived/versioned files can
    never be selected accidentally.  The legacy glob remains only when no
    manifest exists.
    """
    if _GOLD_MANIFEST.exists() and gold_path.name == "ragas_gold.json":
        manifest = json.loads(_GOLD_MANIFEST.read_text(encoding="utf-8"))
        paths = []
        for topic_id in sorted(topic_ids):
            relative = manifest.get("topics", {}).get(topic_id)
            if not relative:
                continue
            path = (gold_path.parent / relative).resolve()
            if path.parent != gold_path.parent.resolve():
                raise ValueError(f"gold manifest trỏ ra ngoài datasets: {relative}")
            if not path.exists():
                raise ValueError(f"gold manifest thiếu file cho {topic_id}: {relative}")
            paths.append(path)
    else:
        paths = [gold_path] if gold_path.exists() else sorted(
            gold_path.parent.glob("independent_gold_pos*.json")
        )
    merged = {}
    for path in paths:
        loaded = load_gold(path)
        merged.update({topic_id: topic for topic_id, topic in loaded.items() if not topic_ids or topic_id in topic_ids})
    return merged


def _load_dataset(path: Path, only: str = "") -> list[dict]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    if only:
        wanted = {item.strip() for item in only.split(",") if item.strip()}
        dataset = [entry for entry in dataset if entry.get("topic_id") in wanted]
    else:
        # Unsupported domains remain callable with --only for diagnostic runs,
        # but must not silently enter the product's core benchmark.
        dataset = [
            entry for entry in dataset
            if entry.get("evaluation_scope", "core") != "unsupported_domain"
        ]
    return dataset


def _write_report(run_dir: Path) -> Path:
    runs, artifacts = load_run(run_dir)
    computed = compute_metrics(runs, artifacts)
    markdown = render_markdown(run_dir, runs, computed)
    report_path = run_dir / "report.md"
    report_path.write_text(markdown, encoding="utf-8")
    (run_dir / "metrics.json").write_text(
        json.dumps(
            {name: metric.as_dict() for name, metric in computed["metrics"].items()},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return report_path


def _expected_counts(records: list[RunRecord]) -> tuple[int, int]:
    """Count only completions and intentional refusals as expected outcomes."""
    intentional_refusals = sum(
        1 for record in records
        if record.outcome == "refused" and record.refusal_kind == "intentional_refusal"
    )
    completed = sum(1 for record in records if record.outcome == "completed")
    return completed + intentional_refusals, intentional_refusals


async def _cmd_run(args: argparse.Namespace) -> int:
    alive, reason = await check_api_alive(args.base_url)
    if not alive:
        print(f"❌ API chưa sẵn sàng — {reason}", file=sys.stderr)
        print("   Khởi động: docker compose up -d backend worker", file=sys.stderr)
        return 2

    dataset = _load_dataset(Path(args.dataset), args.only)
    if not dataset:
        print("❌ Dataset rỗng sau khi lọc --only", file=sys.stderr)
        return 2
    print(f"▶ {len(dataset)} chủ đề × {args.repeat} lần = {len(dataset) * args.repeat} lượt chạy\n")

    run_dir, records = await run_benchmark(
        dataset,
        base_url=args.base_url,
        repeat=args.repeat,
        concurrency=args.concurrency,
        timeout=args.timeout,
        label=args.label,
    )
    saved_runs, artifacts = load_run(run_dir)
    write_corpus_snapshot(run_dir, saved_runs, artifacts)
    report_path = _write_report(run_dir)
    ok, refused = _expected_counts(records)
    print(
        f"\n✅ Xong: {ok}/{len(records)} lượt đúng kỳ vọng"
        + (f" (trong đó {refused} lượt từ chối bịa — đúng thiết kế)" if refused else "")
    )
    print(f"📄 Báo cáo: {report_path}")
    # CI must not treat an infra error disguised as a refusal as a pass.
    return 0 if ok == len(records) else 1


async def _cmd_costs(args: argparse.Namespace) -> int:
    """Lấy chi phí thật từ Langfuse rồi tính lại báo cáo."""
    from benchmarks.external import langfuse_usage

    run_dir = Path(args.run_dir)
    runs_path = run_dir / "runs.json"
    if not runs_path.exists():
        print(f"❌ Không thấy {runs_path}", file=sys.stderr)
        return 2
    runs = json.loads(runs_path.read_text(encoding="utf-8"))
    filled, reason = await langfuse_usage.backfill_run_dir(run_dir, runs)
    if not filled:
        print(f"⚠️ Không lấy được usage cho lượt nào — {reason}", file=sys.stderr)
        return 1
    runs_path.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = _write_report(run_dir)
    print(f"✅ Đã gắn usage cho {filled}/{len(runs)} lượt")
    print(f"📄 Báo cáo: {report_path}")
    return 0


async def _cmd_verify_sources(args: argparse.Namespace) -> int:
    """Tra corpus ở API gốc, lưu vào runs.json rồi tính lại báo cáo."""
    from benchmarks.external import source_check

    run_dir = Path(args.run_dir)
    runs_path = run_dir / "runs.json"
    if not runs_path.exists():
        print(f"❌ Không thấy {runs_path}", file=sys.stderr)
        return 2
    runs = json.loads(runs_path.read_text(encoding="utf-8"))
    print(f"▶ Tra lại paper ở API gốc cho {run_dir.name}", flush=True)
    filled, reason = await source_check.backfill_run_dir(run_dir, runs)
    report_path = _write_report(run_dir)
    if not filled:
        print(f"⚠️ Không tra được lượt nào — {reason}", file=sys.stderr)
        print(f"📄 Báo cáo: {report_path}")
        return 1
    print(f"✅ Đã kiểm nguồn cho {filled}/{len(runs)} lượt")
    print(f"📄 Báo cáo: {report_path}")
    return 0


async def _cmd_ragas(args: argparse.Namespace) -> int:
    """Chấm RAGAS từ artifact đã lưu — không chạy lại pipeline."""
    from benchmarks.external import ragas

    run_dir = Path(args.run_dir)
    if not (run_dir / "runs.json").exists():
        print(f"❌ Không thấy {run_dir}/runs.json", file=sys.stderr)
        return 2
    all_runs, all_artifacts = load_run(run_dir)
    runs, artifacts = all_runs, all_artifacts
    if args.only:
        wanted = {topic_id.strip() for topic_id in args.only.split(",") if topic_id.strip()}
        selected = [
            (record, artifact)
            for record, artifact in zip(all_runs, all_artifacts, strict=True)
            if record.get("topic_id") in wanted
        ]
        runs = [record for record, _ in selected]
        artifacts = [artifact for _, artifact in selected]
        if not runs:
            print(f"❌ Không có topic nào khớp --only={args.only}", file=sys.stderr)
            return 2
    gold_path = Path(args.gold)
    all_topic_ids = {str(record.get("topic_id") or "") for record in all_runs}
    all_reviewed_gold = {}
    try:
        all_reviewed_gold = _load_reviewed_gold_for_topics(gold_path, all_topic_ids)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"❌ Gold không hợp lệ: {exc}", file=sys.stderr)
        return 2
    if not all_reviewed_gold:
        print(
            f"⚠️ Chưa có gold relevance đã review tại {gold_path} hoặc independent_gold_pos*.json — chưa chấm được paper relevance/Context metrics. "
            f"Tạo bằng: python -m benchmarks init-ragas-gold {run_dir}",
            file=sys.stderr,
        )
    reviewed_gold = {
        tid: all_reviewed_gold[tid]
        for tid in {str(record.get("topic_id") or "") for record in runs}
        if tid in all_reviewed_gold
    }
    new_outcomes = await ragas.score_artifacts(runs, artifacts, gold=reviewed_gold, concurrency=args.concurrency)
    outcomes = new_outcomes
    if args.only and (run_dir / "ragas_judgements.json").exists():
        existing_map: dict[str, Any] = {}
        try:
            existing_list = json.loads((run_dir / "ragas_judgements.json").read_text(encoding="utf-8"))
            for item in existing_list:
                existing_map[item["topic_id"]] = ragas.RagasOutcome(
                    topic_id=item["topic_id"],
                    scores=item.get("scores", {}),
                    reasons=item.get("reasons", {}),
                    error=item.get("error"),
                )
        except Exception:
            existing_map = {}
        for outcome in new_outcomes:
            if outcome.topic_id in existing_map:
                merged_scores = dict(existing_map[outcome.topic_id].scores)
                merged_scores.update(outcome.scores)
                merged_reasons = dict(existing_map[outcome.topic_id].reasons)
                merged_reasons.update(outcome.reasons)
                existing_map[outcome.topic_id] = ragas.RagasOutcome(
                    topic_id=outcome.topic_id,
                    scores=merged_scores,
                    reasons=merged_reasons,
                    error=outcome.error if not merged_scores else None,
                )
            else:
                existing_map[outcome.topic_id] = outcome
        outcomes = [
            existing_map[str(r.get("topic_id"))]
            for r in all_runs
            if str(r.get("topic_id")) in existing_map
        ]
        if not outcomes:
            outcomes = new_outcomes
    metrics = ragas.aggregate(outcomes)
    paper_outcomes = compare_paper_gold(all_runs, all_artifacts, all_reviewed_gold)
    paper_metrics = aggregate_paper_gold(paper_outcomes)
    review_metrics = ragas.review_traceability_metrics(all_runs, all_artifacts)
    source_metric = trust.source_resolvability(all_runs)
    (run_dir / "ragas_judgements.json").write_text(
        json.dumps([outcome.as_dict() for outcome in outcomes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "ragas_paper_gold.json").write_text(
        json.dumps([outcome.as_dict() for outcome in paper_outcomes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_path = run_dir / "ragas_report.md"
    report_path.write_text(
        ragas.render_markdown(
            run_dir, outcomes, metrics,
            paper_outcomes=paper_outcomes,
            paper_metrics=paper_metrics,
            review_metrics=review_metrics,
            source_metric=source_metric,
        ),
        encoding="utf-8",
    )
    faithfulness = metrics["faithfulness"]
    print(f"\n{faithfulness.name}: {faithfulness.format_value()}")
    for metric in paper_metrics.values():
        print(f"{metric.name}: {metric.format_value()}")
    print(f"📄 Báo cáo: {report_path}")
    return 0 if faithfulness.measured else 1


def _cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if not (run_dir / "runs.json").exists():
        print(f"❌ Không thấy {run_dir}/runs.json", file=sys.stderr)
        return 2
    report_path = _write_report(run_dir)
    print(report_path.read_text(encoding="utf-8"))
    print(f"\n📄 Đã ghi: {report_path}", file=sys.stderr)
    return 0


def _cmd_snapshot_corpus(args: argparse.Namespace) -> int:
    """Freeze returned-paper metadata for a finished run; no network calls."""
    run_dir = Path(args.run_dir)
    if not (run_dir / "runs.json").exists():
        print(f"❌ Không thấy {run_dir}/runs.json", file=sys.stderr)
        return 2
    runs, artifacts = load_run(run_dir)
    path, snapshot = write_corpus_snapshot(run_dir, runs, artifacts)
    summary = snapshot["summary"]
    print(
        f"✅ Đã freeze corpus: {summary['papers_total']} paper "
        f"({summary['papers_unique']} unique) cho {summary['topics']} topic"
    )
    print(f"📦 Snapshot: {path}")
    return 0


def _cmd_init_ragas_gold(args: argparse.Namespace) -> int:
    """Seed human-reviewable paper gold from a completed baseline run."""
    run_dir = Path(args.run_dir)
    if not (run_dir / "runs.json").exists():
        print(f"❌ Không thấy {run_dir}/runs.json", file=sys.stderr)
        return 2
    target = Path(args.output)
    runs, artifacts = load_run(run_dir)
    try:
        candidate = write_candidate_gold(target, runs, artifacts, source_run=run_dir.name)
    except FileExistsError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    print(f"✅ Đã tạo {len(candidate['topics'])} gold candidate: {target}")
    print("   Reviewer phải chọn/sửa paper_ids, viết reference_answer, rồi đặt reviewed=true.")
    return 0


def _cmd_init_ragas_chunk_gold(args: argparse.Namespace) -> int:
    """Seed reviewable chunk labels from a trace-enabled completed run."""
    run_dir = Path(args.run_dir)
    if not (run_dir / "runs.json").exists():
        print(f"❌ Không thấy {run_dir}/runs.json", file=sys.stderr)
        return 2
    runs, artifacts = load_run(run_dir)
    try:
        candidate = write_chunk_candidate_gold(Path(args.output), runs, artifacts, source_run=run_dir.name)
    except (FileExistsError, ValueError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    print(f"✅ Đã tạo {len(candidate['topics'])} chunk-gold candidate: {args.output}")
    print("   Reviewer duyệt reviewer_label rồi mới dùng làm gold.")
    return 0


def _cmd_auto_label_ragas_chunk_gold(args: argparse.Namespace) -> int:
    """Create transparent proxy labels for one trace-enabled topic/run."""
    target = Path(args.path)
    try:
        payload = write_auto_chunk_labels(target)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    chunks = [
        chunk for topic in payload.get("topics") or []
        for trace in topic.get("traces") or []
        for chunk in trace.get("chunks") or []
    ]
    print(f"✅ Đã auto-label {len(chunks)} chunk bằng {payload['auto_label_policy']}: {target}")
    print("   Đây là proxy nội bộ, không phải human-reviewed gold.")
    return 0


def _cmd_score_ragas_retrieval(args: argparse.Namespace) -> int:
    """Persist auditable retrieval proxy metrics without invoking an LLM."""
    target = Path(args.path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        metrics = score_auto_chunk_retrieval(payload)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    output = Path(args.output) if args.output else target.with_name("retrieval_proxy_metrics.json")
    output.write_text(
        json.dumps({name: metric.as_dict() for name, metric in metrics.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for metric in metrics.values():
        print(f"- {metric.name}: {metric.format_value()}")
    print(f"📦 Metric artifact: {output}")
    return 0


def _cmd_selftest(_args: argparse.Namespace) -> int:
    from benchmarks.selftest import run_selftest

    return run_selftest()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks",
        description="Bộ benchmark: đo chất lượng, độ phủ, hiệu năng và độ tin cậy.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Chạy benchmark trên API đang sống")
    run.add_argument("--base-url", default=DEFAULT_BASE_URL)
    run.add_argument("--dataset", default=str(_DATASET))
    run.add_argument("--only", default="", help="Lọc topic_id, vd: pos_01,neg_01")
    run.add_argument("--repeat", type=int, default=1, help="Số lần lặp mỗi chủ đề (≥2 để đo độ ổn định)")
    run.add_argument("--concurrency", type=int, default=1, help="Số job benchmark song song (khuyến nghị ≤ số key độc lập)")
    run.add_argument("--timeout", type=float, default=1800.0, help="Giới hạn giây cho một lượt")
    run.add_argument("--label", default="", help="Nhãn gắn vào tên thư mục kết quả")
    run.set_defaults(func=lambda a: asyncio.run(_cmd_run(a)))

    report = sub.add_parser("report", help="Tính lại metric từ artifact đã lưu (không chạy lại pipeline)")
    report.add_argument("run_dir")
    report.set_defaults(func=_cmd_report)

    snapshot = sub.add_parser(
        "snapshot-corpus",
        help="Freeze metadata/abstract/rank của paper đã trả về (không tải PDF, không gọi mạng)",
    )
    snapshot.add_argument("run_dir")
    snapshot.set_defaults(func=_cmd_snapshot_corpus)

    costs = sub.add_parser(
        "costs",
        help="Lấy token/chi phí thật từ Langfuse cho một lượt đã chạy, rồi tính lại báo cáo",
    )
    costs.add_argument("run_dir")
    costs.set_defaults(func=lambda a: asyncio.run(_cmd_costs(a)))

    verify = sub.add_parser(
        "verify-sources",
        help="Tra lại từng paper trong corpus ở API gốc (OpenAlex/S2/arXiv), lưu vào runs.json",
    )
    verify.add_argument("run_dir")
    verify.set_defaults(func=lambda a: asyncio.run(_cmd_verify_sources(a)))

    ragas = sub.add_parser(
        "ragas",
        help="Đánh giá paper thật/relevance/evidence-review từ artifact (RAGAS cần evaluator LLM; không chạy lại pipeline)",
    )
    ragas.add_argument("run_dir")
    ragas.add_argument("--gold", default=str(_RAGAS_GOLD), help="Gold relevance paper-level đã reviewer duyệt")
    ragas.add_argument("--concurrency", type=int, default=1, help="Số đánh giá RAGAS song song")
    ragas.add_argument("--only", default="", help="Chỉ chấm các topic_id, vd: pos_01,pos_02")
    ragas.set_defaults(func=lambda a: asyncio.run(_cmd_ragas(a)))

    gold = sub.add_parser(
        "init-ragas-gold",
        help="Tạo candidate gold relevance paper-level từ baseline; phải review thủ công trước khi chấm",
    )
    gold.add_argument("run_dir")
    gold.add_argument("--output", default=str(_RAGAS_GOLD))
    gold.set_defaults(func=_cmd_init_ragas_gold)

    chunk_gold = sub.add_parser(
        "init-ragas-chunk-gold",
        help="Tạo candidate gold chunk từ retrieval_traces; phải review thủ công trước khi chấm",
    )
    chunk_gold.add_argument("run_dir")
    chunk_gold.add_argument("--output", default=str(_RAGAS_CHUNK_GOLD))
    chunk_gold.set_defaults(func=_cmd_init_ragas_chunk_gold)

    auto_chunk_gold = sub.add_parser(
        "auto-label-ragas-chunk-gold",
        help="Tự gán proxy label từ query/chunk; không phải human-reviewed gold",
    )
    auto_chunk_gold.add_argument("path", help="File ragas_chunk_gold.json đã seed")
    auto_chunk_gold.set_defaults(func=_cmd_auto_label_ragas_chunk_gold)

    score_chunk = sub.add_parser(
        "score-ragas-retrieval",
        help="Tính retrieval proxy metric từ chunk auto-label; không gọi API/LLM",
    )
    score_chunk.add_argument("path", help="File chunk gold đã auto-label")
    score_chunk.add_argument("--output", default="", help="Mặc định: retrieval_proxy_metrics.json cạnh file input")
    score_chunk.set_defaults(func=_cmd_score_ragas_retrieval)

    selftest = sub.add_parser("selftest", help="Kiểm tra chính bộ đo — không cần API, không cần DB")
    selftest.set_defaults(func=_cmd_selftest)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
