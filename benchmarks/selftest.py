"""Self-test: prove the measuring instrument works before trusting its numbers.

Every case below plants a *known* defect and asserts the metric catches it, or
plants a clean input and asserts the metric does not cry wolf. A benchmark
nobody has calibrated is just a confident-looking number generator.

Runs fully offline: no API, no database, no network.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from benchmarks import build_gold_from_api, corpus, gold
from benchmarks.external import langfuse_usage, ragas
from benchmarks.metrics import coverage, performance, reliability, trust
from benchmarks.report import compute_metrics, render_markdown

_CLEAN: dict[str, Any] = {
    "papers": [
        {"paper_id": "W1", "abstract": "We  propose   GraphDTA for binding affinity prediction."},
        {"paper_id": "W2", "abstract": "A survey of molecular representation learning."},
    ],
    "references": [
        {"paper_id": "W1", "title": "GraphDTA"},
        {"paper_id": "W2", "title": "Survey"},
    ],
    "themes": [{"title": "Molecular representation learning", "summary_claim_id": "c1"}],
    "claims": [
        {
            "claim_id": "c1", "claim_type": "contribution", "validation_status": "valid",
            "supporting_paper_ids": ["W1", "W2"],
            # Whitespace differs from the abstract on purpose: normalization
            # must treat that as a match, not as fabrication.
            "evidence": [
                {"paper_id": "W1", "quote": "We propose GraphDTA for binding affinity prediction.",
                 "source_level": "abstract"},
            ],
        },
    ],
}

_STATUS: dict[str, Any] = {
    "node_trace": [
        {"node": "queued", "created_at": "2026-08-20T10:00:00+00:00", "papers_found": 0},
        {"node": "search_academic_sources", "created_at": "2026-08-20T10:00:20+00:00", "papers_found": 40},
        {"node": "screen_papers", "created_at": "2026-08-20T10:00:35+00:00", "papers_found": 10},
        {"node": "extract_evidence", "created_at": "2026-08-20T10:04:35+00:00", "papers_found": 10},
    ],
    "ledger": [
        {"stage": "search", "received": 40, "emitted": 10, "dropped": {"trùng nguồn": 30}},
    ],
}


def _with(**overrides: Any) -> dict[str, Any]:
    """Copy the clean fixture with targeted damage applied."""
    import copy

    broken = copy.deepcopy(_CLEAN)
    broken.update(overrides)
    return broken


def _cases() -> list[tuple[str, Callable[[], bool], str]]:
    cases: list[tuple[str, Callable[[], bool], str]] = []

    # --- corpus snapshot: reproducible pre-RAGAS baseline -----------------
    corpus_entries = [
        {"topic_id": "pos_01", "topic": "T", "kind": "positive"},
        {"topic_id": "neg_01", "topic": "N", "kind": "negative_control"},
    ]
    cases.append((
        "Corpus snapshot: --repeat không làm đổi fingerprint dataset",
        lambda: corpus.build_corpus_snapshot(
            [
                {"topic_id": "pos_01", "topic": "T", "kind": "positive", "attempt": 1,
                 "dataset_entry": corpus_entries[0]},
                {"topic_id": "pos_01", "topic": "T", "kind": "positive", "attempt": 2,
                 "dataset_entry": corpus_entries[0]},
            ],
            [{"result": {}}, {"result": {}}],
            source_run="fixture",
        )["dataset"]["sha256"] == corpus.dataset_provenance([corpus_entries[0]])["sha256"],
        "lặp để đo stability không được tạo ra một dataset hash khác",
    ))
    corpus_runs = [
        {"topic_id": "pos_01", "topic": "T", "kind": "positive", "attempt": 1,
         "outcome": "completed", "dataset_entry": corpus_entries[0]},
        {"topic_id": "neg_01", "topic": "N", "kind": "negative_control", "attempt": 1,
         "outcome": "refused", "dataset_entry": corpus_entries[1]},
    ]
    corpus_artifacts = [
        {"result": {"papers": [{"paper_id": "W1", "title": "Paper", "abstract": "A", "rank": 1}]}},
        {"result": {}},
    ]
    cases.append((
        "Corpus snapshot: giữ paper ID, abstract và rank; bỏ negative control",
        lambda: (lambda s: (
            s["summary"] == {"topics": 1, "topics_with_papers": 1, "papers_total": 1, "papers_unique": 1}
            and s["topics"][0]["papers"][0]["paper_id"] == "W1"
            and s["topics"][0]["papers"][0]["rank"] == 1
            and "content_sha256" in s["topics"][0]["papers"][0]
        ))(corpus.build_corpus_snapshot(corpus_runs, corpus_artifacts, source_run="fixture")),
        "snapshot phải tái lập được corpus thật mà pipeline đã trả về",
    ))

    cases.append((
        "Gold relevance candidate luôn cần reviewer duyệt, không tự nhận baseline là ground truth",
        lambda: (lambda candidate: (
            candidate["scope"] == "paper_level_relevance"
            and len(candidate["topics"]) == 1
            and candidate["topics"][0]["paper_ids"] == ["W1"]
            and candidate["topics"][0]["reviewed"] is False
            and candidate["topics"][0]["reference_answer"] == ""
        ))(gold.build_candidate_gold(corpus_runs, corpus_artifacts, source_run="fixture")),
        "baseline trả về không được tự phong là gold; người review phải xác nhận nó",
    ))
    trace_artifacts = [{"result": {"retrieval_traces": [{
        "stage": "validate_grounding", "query": "Q", "paper_filter": ["W1"],
        "selected_document_ids": ["W1:chunk:0"],
        "ranked_chunks": [{
            "document_id": "W1:chunk:0", "paper_id": "W1", "content_hash": "hash",
            "rank": 1, "retrieval_score": 0.9, "quote": "Evidence",
        }],
    }]}}]
    cases.append((
        "Chunk gold candidate giữ rank/provenance và chỉ gợi ý nhãn, không tự freeze gold",
        lambda: (lambda candidate: (
            candidate["scope"] == "chunk_level_relevance_candidate"
            and candidate["topics"][0]["reviewed"] is False
            and candidate["topics"][0]["traces"][0]["chunks"][0]["suggested_label"] == "likely_relevant"
            and candidate["topics"][0]["traces"][0]["chunks"][0]["reviewer_label"] is None
        ))(gold.build_chunk_candidate_gold(corpus_runs[:1], trace_artifacts, source_run="fixture")),
        "chunk retrieval do hệ thống trả về chỉ là candidate để reviewer duyệt, không phải ground truth",
    ))
    cases.append((
        "Chunk auto-label và retrieval proxy không tự bịa Recall@K",
        lambda: (lambda payload: (
            payload["scope"] == "chunk_level_relevance_auto_labeled"
            and payload["topics"][0]["traces"][0]["chunks"][0]["auto_label"] == "relevant"
            and gold.score_auto_chunk_retrieval(payload)["precision_at_1"].value == 1.0
            and gold.score_auto_chunk_retrieval(payload)["recall_at_5"].measured is False
        ))(gold.auto_label_chunk_candidate({
            "schema_version": 1,
            "scope": "chunk_level_relevance_candidate",
            "topics": [{"traces": [{
                "query": "graph neural networks molecular prediction",
                "chunks": [{"rank": 1, "quote": "Graph neural networks improve molecular prediction."}],
            }]}],
        })),
        "top-K trace không chứa relevant chunk bị bỏ sót nên Recall@K phải giữ unmeasured",
    ))

    def _gold_is_reviewed_before_use() -> bool:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ragas_gold.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "topics": [{
                    "topic_id": "pos_01", "paper_ids": ["W1", "W2"],
                    "reference_answer": "Một reference do người viết.", "reviewed": True,
                }],
            }), encoding="utf-8")
            loaded = gold.load_gold(path)
            return (
                loaded["pos_01"].paper_ids == ("W1", "W2")
                and loaded["pos_01"].reference_answer == "Một reference do người viết."
            )

    cases.append((
        "Gold relevance chỉ được dùng sau reviewed=true",
        _gold_is_reviewed_before_use,
        "gold chưa reviewer duyệt không được làm ground truth cho Context Recall",
    ))

    def _gold_is_never_overwritten() -> bool:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ragas_gold.json"
            path.write_text("{}", encoding="utf-8")
            try:
                gold.write_candidate_gold(path, corpus_runs, corpus_artifacts, source_run="fixture")
            except FileExistsError:
                return path.read_text(encoding="utf-8") == "{}"
            return False

    cases.append((
        "Gold relevance đã tồn tại → lệnh seed từ chối ghi đè",
        _gold_is_never_overwritten,
        "retrieval live không được vô tình thay đổi baseline đã review",
    ))

    traffic_topic = {
        "topic": "Graph neural networks for traffic forecasting",
        "expected_themes": ["Traffic forecasting", "Dynamic graph modeling"],
    }
    mamba_topic = {
        "topic": "Mamba architectures for long-context language modeling",
        "expected_themes": ["Selective state space models", "Long-context modeling"],
    }
    cases.append((
        "Gold API curator loại network/backend traffic khỏi traffic forecasting",
        lambda: build_gold_from_api.auto_label({
            "title": "Traffic Prediction in Distributed Backend Systems with Graph Networks",
            "abstract": "Predicts internet traffic and packet load in data center backend systems.",
        }, traffic_topic, "pos_01")[0] == "irrelevant",
        "từ traffic trong mạng máy tính không được biến thành gold giao thông đường bộ",
    ))
    cases.append((
        "Gold API curator giữ đúng GNN dự báo giao thông đường bộ",
        lambda: build_gold_from_api.auto_label({
            "title": "Spatio-Temporal Graph Neural Networks for Traffic Forecasting",
            "abstract": "A graph convolution model predicts traffic flow over road sensor networks.",
        }, traffic_topic, "pos_01")[0] == "relevant",
        "domain gate không được loại paper đúng chủ đề",
    ))
    cases.append((
        "Gold API curator loại Vision Mamba khỏi long-context language modeling",
        lambda: build_gold_from_api.auto_label({
            "title": "Vision Mamba for Medical Image Segmentation",
            "abstract": "A selective state space model segments medical images.",
        }, mamba_topic, "pos_02")[0] == "irrelevant",
        "có chữ Mamba không đủ để trở thành paper về language model",
    ))
    cases.append((
        "Gold API curator loại protein-language Mamba khỏi long-context NLP",
        lambda: build_gold_from_api.auto_label({
            "title": "PTM-Mamba: A Protein Language Model",
            "abstract": "A bidirectional selective state space model processes long protein sequences.",
        }, mamba_topic, "pos_02")[0] == "irrelevant",
        "protein language không phải natural-language long-context modeling",
    ))
    cases.append((
        "Gold API curator giữ Mamba language model dù lexical score chung thấp",
        lambda: build_gold_from_api.auto_label({
            "title": "Samba: Hybrid Mamba Models for Unlimited Context",
            "abstract": "A selective state space language model processes long sequences with token-level recall.",
        }, mamba_topic, "pos_02")[0] == "relevant",
        "domain gate đầy đủ phải quyết định relevance thay vì ngưỡng keyword chung",
    ))
    cases.append((
        "Gold API curator giữ paper Mamba nền tảng cho theme long-sequence",
        lambda: build_gold_from_api.auto_label({
            "title": "Mamba: Linear-Time Sequence Modeling with Selective State Spaces",
            "abstract": "A selective state space sequence model scales linearly to long sequences.",
        }, mamba_topic, "pos_02")[0] == "relevant",
        "mỗi paper chỉ cần support một theme; không bắt một paper phủ cả ba theme",
    ))
    cases.append((
        "Gold API curator luôn giữ topic gốc và query mở rộng khi system có nhiều query",
        lambda: (lambda queries: (
            mamba_topic["topic"] in queries
            and "Mamba Linear-Time Sequence Modeling Selective State Spaces language modeling" in queries
            and len(queries) <= 10
        ))(build_gold_from_api.build_queries(
            [f"system query {index}" for index in range(10)], mamba_topic, "pos_02",
        )),
        "query_history không được chiếm hết candidate pool và loại mất independent expansion",
    ))
    cases.append((
        "Gold API curator dedupe cùng paper giữa OpenAlex và arXiv, ưu tiên arXiv ID",
        lambda: build_gold_from_api.dedupe_candidates([
            {"paper_id": "openalex:W1", "title": "ReMamba: Long-Sequence Modeling"},
            {"paper_id": "arxiv:2408.15496", "title": "ReMamba: Long-Sequence Modeling"},
        ]) == [{"paper_id": "arxiv:2408.15496", "title": "ReMamba: Long-Sequence Modeling"}],
        "duplicate cross-provider không được làm tăng mẫu số gold",
    ))

    def _api_gold_is_fail_closed_and_loadable() -> bool:
        paper = {
            "paper_id": "arxiv:1", "title": "T", "authors": "A", "year": 2024,
            "label": "relevant", "label_reason": "reviewed", "label_score": 1.0,
            "validated": True, "val_note": "title_overlap=1.00",
            "abstract": "Graph neural networks model spatial road dependencies for traffic forecasting.",
            "url": "https://arxiv.org/abs/1", "source": "arxiv",
        }
        payload = build_gold_from_api.freeze_gold(
            "pos_01", traffic_topic, [paper], [traffic_topic["topic"]],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gold.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            loaded = gold.load_gold(path)
        try:
            build_gold_from_api.freeze_gold(
                "pos_01", traffic_topic, [{**paper, "validated": False}], [traffic_topic["topic"]],
            )
        except ValueError:
            rejected_unvalidated = True
        else:
            rejected_unvalidated = False
        reference = payload["topics"][0]["reference_answer"]
        return (
            payload["schema_version"] == 1
            and "pos_01" in loaded
            and loaded["pos_01"].precision_judged is False
            and rejected_unvalidated
            and "Graph neural networks model spatial road dependencies" in reference
            and "should synthesize evidence across" not in reference
        )

    cases.append((
        "Gold API curator chỉ freeze paper validated và tạo schema loader đọc được",
        _api_gold_is_fail_closed_and_loadable,
        "API lỗi hoặc schema lệch không được tạo gold tưởng là dùng được",
    ))
    cases.append((
        "Gold reference không lấy câu abstract bị cắt cụt",
        lambda: build_gold_from_api.build_reference_answer(
            traffic_topic,
            [{
                "paper_id": "arxiv:1",
                "abstract": (
                    "Graph neural networks model road dependencies for traffic forecasting. "
                    "This trailing sentence was truncated before it could finish"
                ),
            }],
        ) == "Graph neural networks model road dependencies for traffic forecasting. [arxiv:1]",
        "reference_answer không được biến đoạn abstract bị truncate thành gold claim",
    ))

    paper_gold = {"pos_01": gold.GoldTopic("pos_01", ("W1", "W3"), "Reference")}
    paper_runs = [{"topic_id": "pos_01", "kind": "positive", "outcome": "completed"}]
    paper_outcomes = gold.compare_paper_gold(paper_runs, [{"result": _CLEAN}], paper_gold)
    cases.append((
        "Gold relevance precision/recall bắt đúng paper thiếu và paper thừa",
        lambda: (
            gold.aggregate_paper_gold(paper_outcomes)["paper_precision"].value == 0.5
            and gold.aggregate_paper_gold(paper_outcomes)["paper_recall"].value == 0.5
            and paper_outcomes[0].matched_paper_ids == ("W1",)
        ),
        "paper-level metric phải là đối chiếu ID tất định, không gọi LLM để phán đoán ID",
    ))

    def _paper_gold_matches_provider_alias_and_keeps_precision_unmeasured() -> bool:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gold.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "topics": [{
                    "topic_id": "pos_02",
                    "paper_ids": ["arxiv:2406.07522"],
                    "paper_relevance": [{
                        "paper_id": "arxiv:2406.07522",
                        "title": "Samba: Simple Hybrid State Space Models for Efficient Unlimited Context Language Modeling",
                    }],
                    "reference_answer": "Reference.",
                    "reviewed": True,
                }],
            }), encoding="utf-8")
            loaded = gold.load_gold(path)
        outcomes = gold.compare_paper_gold(
            [{"topic_id": "pos_02", "kind": "positive", "outcome": "completed"}],
            [{"result": {"papers": [{
                "paper_id": "s2:provider_alias",
                "title": "Samba: Simple Hybrid State Space Models for Efficient Unlimited Context Language Modeling",
            }]} }],
            loaded,
        )
        metrics = gold.aggregate_paper_gold(outcomes)
        return (
            outcomes[0].matched_paper_ids == ("s2:provider_alias",)
            and outcomes[0].matched_gold_paper_ids == ("arxiv:2406.07522",)
            and metrics["paper_recall"].value == 1.0
            and metrics["paper_precision"].measured is False
        )

    cases.append((
        "Paper gold match provider alias bằng metadata; gold positive-only không báo precision giả",
        _paper_gold_matches_provider_alias_and_keeps_precision_unmeasured,
        "khác ID giữa arXiv/OpenAlex/Semantic Scholar không được biến paper đúng thành false negative",
    ))

    from benchmarks.runner import _write_json_atomically

    def _atomic_json_write() -> bool:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "run_env.json"
            _write_json_atomically(target, {"version": 1})
            _write_json_atomically(target, {"version": 2})
            return (
                json.loads(target.read_text(encoding="utf-8")) == {"version": 2}
                and not target.with_suffix(".json.tmp").exists()
            )

    cases.append((
        "run_env/runs JSON ghi atomically qua temporary file",
        _atomic_json_write,
        "crash giữa lúc ghi không được để lại JSON đứt đoạn làm hỏng report",
    ))

    # --- trust -------------------------------------------------------------
    cases.append((
        "Kết quả sạch → không báo trích dẫn bịa",
        lambda: trust.fabricated_citation_rate(_CLEAN).value == 0.0,
        "báo động giả sẽ khiến mọi cảnh báo thật bị bỏ qua",
    ))
    fabricated = _with(claims=[{
        "claim_id": "cX", "validation_status": "valid",
        "supporting_paper_ids": ["W_KHONG_TON_TAI"],
        "evidence": [{"paper_id": "W_KHONG_TON_TAI", "quote": "bịa", "source_level": "abstract"}],
    }])
    cases.append((
        "Trích dẫn paper không có trong corpus → BỊ BẮT",
        lambda: trust.fabricated_citation_rate(fabricated).value == 1.0,
        "đây là tín hiệu bịa đặt rõ ràng nhất, bỏ sót là hỏng cả bộ đo",
    ))
    review_backed = _with(literature_review={
        "title": "GraphDTA", "abstract": "GraphDTA dự đoán affinity [[W1]].",
        "introduction": "Học biểu diễn phân tử là trọng tâm [[W1]].",
        "sections": [{"title": "Kết quả", "paragraphs": ["GraphDTA dùng evidence từ paper gốc [[W1]]."]}],
        "conclusion": "Kết quả nhất quán với paper [[W1]].", "limitations": "Corpus còn hẹp [[W1]].",
    })
    cases.append((
        "Citation trong literature review trỏ đúng paper đã lấy",
        lambda: trust.review_citation_validity(review_backed).value == 1.0,
        "không được chỉ kiểm citation của claim trung gian rồi bỏ qua prose người dùng đọc",
    ))
    review_unknown_paper = _with(literature_review={
        "title": "Sai nguồn", "abstract": "Nhận định [[W_KHONG_TON_TAI]].", "sections": [],
    })
    cases.append((
        "Citation bịa trong literature review → BỊ BẮT",
        lambda: trust.review_citation_validity(review_unknown_paper).value == 0.0,
        "paper_id lạ trong bài review cuối là lỗi traceability trực tiếp",
    ))
    cases.append((
        "Mỗi đoạn review có citation nối tới evidence quote → đạt coverage",
        lambda: trust.review_evidence_coverage(review_backed).value == 1.0,
        "đường review → paper → quote phải kiểm được offline trước khi gọi LLM judge",
    ))
    review_unbacked = _with(literature_review={
        "title": "Không evidence", "abstract": "Survey được nhắc tới [[W2]].", "sections": [],
    })
    cases.append((
        "Citation review không có quote evidence cùng paper → BỊ BẮT",
        lambda: trust.review_evidence_coverage(review_unbacked).value == 0.0,
        "citation chỉ tồn tại trong corpus chưa đủ chứng minh evidence đã đi vào bài review",
    ))
    ungrounded = _with(claims=[{
        "claim_id": "cY", "validation_status": "valid", "supporting_paper_ids": ["W1"], "evidence": [],
    }])
    cases.append((
        "Claim hợp lệ nhưng rỗng bằng chứng → BỊ BẮT",
        lambda: trust.claim_grounding_rate(ungrounded).value == 0.0,
        "claim không nguồn mà mang nhãn hợp lệ là dạng sai nguy hiểm nhất",
    ))
    mismatched = _with(claims=[{
        "claim_id": "cZ", "validation_status": "valid", "supporting_paper_ids": ["W1"],
        "evidence": [{"paper_id": "W1", "quote": "Câu này không hề có trong abstract.",
                      "source_level": "abstract"}],
    }])
    cases.append((
        "Quote không khớp nguồn → BỊ BẮT",
        lambda: trust.quote_verifiability(mismatched).value == 0.0,
        "trích sai lời tác giả vẫn là sai dù paper có thật",
    ))
    cases.append((
        "Quote khác khoảng trắng vẫn tính là khớp",
        lambda: trust.quote_verifiability(_CLEAN).value == 1.0,
        "khác định dạng khi bóc PDF không phải là bịa",
    ))
    fulltext = _with(claims=[{
        "claim_id": "cF", "validation_status": "valid", "supporting_paper_ids": ["W1"],
        "evidence": [{"paper_id": "W1", "quote": "Đoạn nằm sâu trong full text.",
                      "source_level": "full_text"}],
    }])
    cases.append((
        "Quote full-text → đánh dấu KHÔNG kiểm được, không tính pass/fail",
        lambda: not trust.quote_verifiability(fulltext).measured,
        "nhận là đã kiểm thứ mình không đọc được chính là kiểu gian lận bộ đo này sinh ra để chặn",
    ))
    cases.append((
        "Chủ đề vô nghĩa trả rỗng → đạt",
        lambda: trust.negative_control(papers=0, valid_claims=0).value == 1.0,
        "hệ thống phải biết nói 'không có gì'",
    ))
    cases.append((
        "Chủ đề vô nghĩa vẫn ra kết quả → trượt",
        lambda: trust.negative_control(papers=5, valid_claims=3).value == 0.0,
        "luôn tìm ra thứ gì đó là dấu hiệu của máy sinh văn bản, không phải công cụ nghiên cứu",
    ))
    # Hồi quy: lỗi THẬT của harness, phát hiện khi chạy live lần đầu.
    # Hệ thống từ chối bịa bằng cách kết thúc ở trạng thái `error`; bản runner
    # đầu tiên chấm đó là "thất bại", tức phạt sản phẩm vì đã trung thực.
    cases.append((
        "Từ chối bịa (job báo error, output rỗng) → vẫn tính ĐẠT",
        lambda: trust.negative_control(papers=0, valid_claims=0, pipeline_outcome="refused").value == 1.0,
        "đây là lỗi harness đã gặp thật: phạt sản phẩm vì nó trung thực nói 'không có gì'",
    ))
    cases.append((
        "Kiểm soát âm không bị tính vào tỷ lệ chạy thành công",
        lambda: reliability.success_rate([
            {"topic": "A", "kind": "positive", "outcome": "completed"},
            {"topic": "N", "kind": "negative_control", "outcome": "refused"},
        ]).value == 1.0,
        "gộp chung sẽ khiến hệ thống từ chối đúng cách trông như kém tin cậy",
    ))

    # --- không bịa số khi thiếu dữ liệu -----------------------------------
    # Hồi quy: lỗi THẬT của bộ đo, phát hiện ở lượt chạy n=10 (2026-08-20).
    # Claim `potential_gap` khẳng định sự VẮNG MẶT — bằng chứng của nó là chính
    # corpus, nên không có quote theo đúng thiết kế. Bản đo đầu tiên đòi quote
    # cho cả loại này, kéo `claim_grounding_rate` từ 100% xuống 97.9% và biến
    # hành vi đúng thành khuyết tật.
    gap_claim = _with(claims=[{
        "claim_id": "cG", "claim_type": "potential_gap", "validation_status": "valid",
        "supporting_paper_ids": ["W1"], "evidence": [],
        "text": "Trong 14 bài thu thập, chưa thấy đánh giá trên bệnh nhân nhi.",
    }])
    cases.append((
        "Claim `potential_gap` không quote → KHÔNG bị tính là thiếu bằng chứng",
        lambda: not trust.claim_grounding_rate(gap_claim).measured,
        "claim về sự vắng mặt lấy corpus làm bằng chứng; đòi quote là báo oan hành vi đúng",
    ))
    mixed_gap = _with(claims=[
        {"claim_id": "cG", "claim_type": "potential_gap", "validation_status": "valid",
         "supporting_paper_ids": ["W1"], "evidence": []},
        {"claim_id": "cC", "claim_type": "contribution", "validation_status": "valid",
         "supporting_paper_ids": ["W1"], "evidence": []},
    ])
    cases.append((
        "Claim `contribution` không quote → VẪN BỊ BẮT (miễn trừ không lan sang loại khác)",
        lambda: mixed_gap and trust.claim_grounding_rate(mixed_gap).value == 0.0
        and trust.claim_grounding_rate(mixed_gap).denominator == 1,
        "nới cho potential_gap mà nới luôn cả bộ thì bộ đo mất hết răng",
    ))

    cases.append((
        "0/0 → 'chưa đo được', KHÔNG phải 0% hay 100%",
        lambda: not trust.claim_grounding_rate({"claims": []}).measured,
        "0/0 quy thành 0% sẽ âm thầm kéo tụt mọi số trung bình tính trên nó",
    ))
    cases.append((
        "Chưa có baseline thủ công → không tự bịa mức tiết kiệm",
        lambda: not performance.human_time_saved(_STATUS, manual_minutes=None).measured,
        "đây là con số dễ bị hỏi vặn nhất trong một buổi pitch",
    ))
    cases.append((
        "Chưa bật đo token → không tự bịa chi phí",
        lambda: not performance.cost_per_review(_STATUS).measured,
        "một con số chi phí sai sẽ sống rất lâu trong slide gọi vốn",
    ))

    # --- coverage ----------------------------------------------------------
    cases.append((
        "Theme khớp một phần vẫn tính đúng độ phủ",
        lambda: coverage.theme_recall(_CLEAN, ["Molecular representation", "Sinh phân tử"]).value == 0.5,
        "đo phải bắt được 'bỏ sót cả mảng', không phải chấm cách diễn đạt",
    ))
    cases.append((
        "Dataset không khai expected_themes → chưa đo, không phải 0%",
        lambda: not coverage.theme_recall(_CLEAN, []).measured,
        "thiếu nhãn vàng là thiếu phép đo, không phải điểm kém",
    ))
    ingestion_fixture = _with(papers=[
        {
            "paper_id": "W_FULL", "ingestion": {
                "content_availability": "full_text", "ingestion_status": "succeeded",
                "full_text_source": "pdf", "full_text_url": "https://example.test/full.pdf",
                "full_text_chunks": 12, "ingestion_warning": None,
            },
        },
        {
            "paper_id": "W_ABSTRACT", "ingestion": {
                "content_availability": "abstract_only", "ingestion_status": "unavailable",
                "full_text_source": None, "full_text_url": None,
                "full_text_chunks": 0, "ingestion_warning": "PDF_UNAVAILABLE:W_ABSTRACT",
            },
        },
        {
            "paper_id": "W_FAILED", "ingestion": {
                "content_availability": "abstract_only", "ingestion_status": "failed",
                "full_text_source": None, "full_text_url": None,
                "full_text_chunks": 0, "ingestion_warning": "PDF_FALLBACK:W_FAILED:403",
            },
        },
    ])
    cases.append((
        "Metadata P0 phân loại đúng full text / unavailable / ingestion failed",
        lambda: (lambda metrics: (
            metrics["Đủ metadata ingestion cho paper"].value == 1.0
            and metrics["Paper có full text"].value == 1 / 3
            and metrics["Paper chỉ có abstract (không khả dụng)"].value == 1 / 3
            and metrics["Paper fallback do lỗi ingestion"].value == 1 / 3
        ))({metric.name: metric for metric in coverage.paper_ingestion_metrics(ingestion_fixture)}),
        "availability của paper phải tách khỏi evidence usage và nguyên nhân fallback",
    ))
    cases.append((
        "Artifact cũ thiếu metadata ingestion → chưa đo, không mặc định abstract-only",
        lambda: all(not metric.measured for metric in coverage.paper_ingestion_metrics(_CLEAN)),
        "đoán paper cũ là abstract-only sẽ tạo ra số xấu giả từ dữ liệu chưa từng được lưu",
    ))
    malformed_ingestion = _with(papers=[{
        "paper_id": "W_BAD", "ingestion": {
            "content_availability": "full_text", "ingestion_status": "succeeded",
            "full_text_source": None, "full_text_url": None,
            "full_text_chunks": 0, "ingestion_warning": None,
        },
    }])
    cases.append((
        "Metadata P0 có nhãn full_text nhưng thiếu source/chunk → chưa đo, không cho qua",
        lambda: all(not metric.measured for metric in coverage.paper_ingestion_metrics(malformed_ingestion)),
        "chỉ tin hai nhãn trạng thái sẽ cho metadata rỗng làm đẹp tỷ lệ full text",
    ))
    # Hồi quy: lỗi THẬT của bộ đo, cùng lượt chạy n=10. `themes` rỗng ở 4/6
    # lượt trong khi `literature_review` luôn đầy đủ — bản đo đầu tiên chỉ nhìn
    # `themes` nên báo độ phủ 43.8% cho những bài review thực ra đã phủ đúng.
    review_only = _with(themes=[], claims=[], literature_review={
        "title": "Molecular representation learning for drug discovery",
        "abstract": "",
        "introduction": "",
        "sections": [{"title": "Đại diện phân tử",
                      "paragraphs": ["Các phương pháp molecular representation được so sánh."]}],
        "conclusion": "", "limitations": "",
    })
    cases.append((
        "`themes` rỗng nhưng bài review có phủ chủ đề → tính là ĐÃ PHỦ",
        lambda: coverage.theme_recall(review_only, ["Molecular representation"]).value == 1.0,
        "đo sai trường không phân biệt được với sản phẩm kém, cho tới khi có người mở artifact ra đọc",
    ))
    claim_only = _with(themes=[], literature_review={
        "title": "Clinical time-series forecasting", "abstract": "", "introduction": "",
        "sections": [], "conclusion": "", "limitations": "",
    }, claims=[{
        "claim_id": "c1", "claim_type": "contribution", "validation_status": "valid",
        "text": "Các state space model đạt kết quả tốt trên chuỗi thời gian dài.",
        "supporting_paper_ids": ["W1"], "evidence": [],
    }])
    cases.append((
        "Chủ đề chỉ xuất hiện trong claim (review không nhắc) → vẫn tính là ĐÃ PHỦ",
        lambda: coverage.theme_recall(claim_only, ["State space models"]).value == 1.0,
        "claim cũng là đầu ra người dùng đọc; bỏ qua nó là lặp lại đúng lỗi 'đo sai trường'",
    ))
    corpus_only = _with(themes=[], claims=[], literature_review={
        "title": "Không liên quan", "abstract": "", "introduction": "",
        "sections": [], "conclusion": "", "limitations": "",
    }, papers=[{"paper_id": "W9", "abstract": "A study of federated learning privacy attacks."}])
    cases.append((
        "Chủ đề chỉ nằm trong corpus đã tải, không có trong đầu ra → KHÔNG tính là phủ",
        lambda: coverage.theme_recall(corpus_only, ["Federated learning privacy attacks"]).value == 0.0,
        "tải được bài về chủ đề không đồng nghĩa với việc bài review đã viết về nó",
    ))

    cases.append((
        "Bài tải về mà không trích dẫn → tính đúng tỷ lệ lãng phí",
        lambda: coverage.citation_reuse(_CLEAN).value == 1.0,
        "tải 20 dùng 3 là chi phí thật đang chảy đi đâu",
    ))

    # --- RAGAS (lớp LLM-judge, adapter phải chạy offline được) ------------
    ragas_record = {
        "topic_id": "ragas_01",
        "topic": "Graph neural networks in drug discovery",
        "outcome": "completed",
        "dataset_entry": {"reference_answer": "Graph neural networks learn molecular representations."},
    }
    ragas_artifact = {"result": _with(literature_review={
        "title": "Graph neural networks", "abstract": "", "introduction": "",
        "sections": [{"title": "Findings", "paragraphs": ["GraphDTA predicts binding affinity."]}],
        "conclusion": "", "limitations": "",
    })}
    cases.append((
        "RAGAS adapter chỉ lấy review cuối và evidence quote, không nhét abstract/claim vào answer",
        lambda: (lambda sample: sample is not None and "GraphDTA predicts" in sample.response
                and "We propose GraphDTA" in sample.retrieved_contexts[0])(
            ragas.sample_from_artifact(ragas_record, ragas_artifact)[0]
        ),
        "đưa abstract corpus vào answer sẽ khiến tầng retrieval tự chấm điểm cho chính nó",
    ))
    cases.append((
        "RAGAS không dùng claim trung gian làm câu trả lời để chấm",
        lambda: ragas.answer_text(_with(literature_review=None)) == "",
        "claim hợp lệ không phải literature review mà người dùng nhận; đưa nó vào answer sẽ làm lệch Faithfulness",
    ))
    cases.append((
        "RAGAS ưu tiên reference_answer đã review trong gold thay vì dataset cũ",
        lambda: (
            ragas.sample_from_artifact(
                ragas_record, ragas_artifact,
                gold=gold.GoldTopic("ragas_01", ("W1",), "Reference đã review"),
            )[0].reference == "Reference đã review"  # type: ignore[union-attr]
        ),
        "reference do reviewer freeze là ground truth; không được để fixture dataset vô tình thay thế nó",
    ))
    cases.append((
        "Thiếu evidence quote → RAGAS báo chưa chấm được, không dựng score 0%",
        lambda: ragas.sample_from_artifact(
            ragas_record, {"result": _with(claims=[], literature_review={"title": "Có review", "sections": []})},
        )[0] is None,
        "không có context thì Faithfulness không có nghĩa; 0% ở đây là số bịa",
    ))
    ragas_outcomes = [
        ragas.RagasOutcome("q1", scores={"faithfulness": 0.95, "context_precision": 0.82, "context_recall": 0.75}),
        ragas.RagasOutcome("q2", scores={"faithfulness": 0.85}),
    ]
    cases.append((
        "RAGAS gộp điểm theo metric, giữ Context Recall thiếu reference là chưa đo chứ không kéo thành 0",
        lambda: (
            abs((ragas.aggregate(ragas_outcomes)["faithfulness"].value or 0.0) - 0.90) < 1e-9
            and ragas.aggregate(ragas_outcomes)["context_recall"].value == 0.75
            and ragas.aggregate(ragas_outcomes)["context_precision"].value == 0.82
        ),
        "một topic không có reference_answer không được biến thành một lần Context Recall trượt",
    ))
    cases.append((
        "RAGAS traceability gộp citation/evidence từ prose review cuối",
        lambda: (
            ragas.review_traceability_metrics(
                [{"kind": "positive", "outcome": "completed"}], [{"result": review_backed}],
            )["Đoạn review có evidence truy vết được"].value == 1.0
        ),
        "báo cáo RAGAS phải kèm kiểm tra tất định, không chỉ một điểm LLM-as-judge",
    ))
    cases.append((
        "RAGAS report tách paper thật, relevance và evidence→review",
        lambda: (lambda report: (
            "## 1. Paper có tồn tại thật?" in report
            and "## 2. Paper có liên quan chủ đề?" in report
            and "## 3. Evidence từ paper có đi vào literature review?" in report
            and "## 4. RAGAS: evidence có support nội dung review?" in report
        ))(ragas.render_markdown(
            Path("fixture"), [], ragas.aggregate([]),
            paper_metrics=gold.aggregate_paper_gold([]),
            review_metrics=ragas.review_traceability_metrics(
                [{"kind": "positive", "outcome": "completed"}], [{"result": review_backed}],
            ),
        )),
        "một điểm Faithfulness không được che khuất hai câu hỏi paper thật và paper liên quan",
    ))
    # --- Langfuse (nguồn dữ liệu chi phí) ----------------------------------
    def _trace(generations: list[dict[str, Any]]) -> dict[str, Any]:
        return {"observations": [{"type": "GENERATION", **g} for g in generations]}

    cases.append((
        "Trace có token và giá → gộp đúng chi phí, token và số lời gọi",
        lambda: langfuse_usage.summarise_trace(_trace([
            {"calculatedTotalCost": 0.01, "usage": {"total": 100}, "model": "m"},
            {"calculatedTotalCost": 0.02, "usage": {"total": 200}, "model": "m"},
        ])) == {"total_cost_usd": 0.03, "total_tokens": 300, "call_count": 2, "models": ["m"]},
        "đây là con số nhà đầu tư hỏi đầu tiên; cộng sai thì sai suốt",
    ))
    cases.append((
        "Chi phí = 0 dù có lời gọi → 'chưa đo được', KHÔNG phải miễn phí",
        lambda: (langfuse_usage.summarise_trace(_trace([
            {"calculatedTotalCost": 0, "usage": {"total": 500}, "model": "m"},
        ])) or {}).get("total_cost_usd") is None,
        "in $0.0000 vì Langfuse thiếu bảng giá là một số sai trông rất thuyết phục",
    ))
    cases.append((
        "Trace không có lời gọi LLM nào → None, không dựng ra bản ghi rỗng",
        lambda: langfuse_usage.summarise_trace({"observations": [{"type": "SPAN"}]}) is None,
        "không có gì để đo thì phải nói thế, không báo 0 đồng",
    ))
    cases.append((
        "Chi phí = 0 vẫn giữ lại token và LÝ DO để truy được nguyên nhân",
        lambda: "bảng giá" in (langfuse_usage.summarise_trace(_trace([
            {"calculatedTotalCost": 0, "usage": {"total": 500}, "model": "m"},
        ])) or {}).get("unmeasured_reason", ""),
        "'chưa đo được' mà không kèm lý do thì phiên sau lại phải mò lại từ đầu",
    ))

    # --- performance -------------------------------------------------------
    cases.append((
        "Latency loại bỏ thời gian chờ người duyệt",
        lambda: performance.total_latency(_STATUS).value == 275.0,
        "tính cả thời gian người đi ăn trưa thì không còn là số đo sản phẩm",
    ))
    cases.append((
        "Chỉ đúng chặng chậm nhất",
        lambda: "extract_evidence" in performance.bottleneck(_STATUS).detail,
        "đây là chỗ một giờ tối ưu đem lại nhiều nhất",
    ))
    cases.append((
        "Thời gian tới kết quả đầu tiên tính từ lúc có bài đầu tiên",
        lambda: performance.time_to_first_output(_STATUS).value == 20.0,
        "đo đúng cảm giác chờ của người dùng, khác tổng thời gian chạy",
    ))

    # --- reliability -------------------------------------------------------
    runs = [
        {"topic": "A", "outcome": "completed", "latency_seconds": 100.0, "valid_claims": 10},
        {"topic": "A", "outcome": "completed", "latency_seconds": 300.0, "valid_claims": 10},
        {"topic": "B", "outcome": "failed", "error_class": "TimeoutError", "error": "hết giờ"},
    ]
    cases.append((
        "Tỷ lệ thành công tính đúng",
        lambda: abs(reliability.success_rate(runs).value - 2 / 3) < 1e-9,
        "",
    ))
    cases.append((
        "Chủ đề thật trả rỗng → KHÔNG tính vào tỷ lệ thành công",
        lambda: reliability.success_rate(
            runs + [{"topic": "C", "outcome": "empty_result"}]
        ).value < 2 / 3,
        "hệ thống chạy xong mà trả 0 bài 0 claim cho chủ đề thật là thất bại bị ẩn trong 100%",
    ))
    cases.append((
        "Lỗi được gom theo nguyên nhân",
        lambda: reliability.failure_taxonomy(runs)[0]["cause"] == "TimeoutError",
        "một lỗi lặp 15 lần khác hẳn 15 lỗi khác nhau",
    ))
    cases.append((
        "Đầu ra ổn định giữa các lần lặp → 100%",
        lambda: reliability.output_consistency(runs).value == 1.0,
        "",
    ))
    unstable = [
        {"topic": "A", "outcome": "completed", "latency_seconds": 100.0, "valid_claims": 12},
        {"topic": "A", "outcome": "completed", "latency_seconds": 100.0, "valid_claims": 3},
    ]
    cases.append((
        "Đầu ra dao động mạnh → điểm ổn định tụt",
        lambda: reliability.output_consistency(unstable).value < 0.5,
        "12 claim lần này, 3 claim lần sau là không dùng được, dù từng claim đều có nguồn",
    ))

    # --- báo cáo đầu-cuối ---------------------------------------------------
    def _report_renders() -> bool:
        run_records = [
            {"topic_id": "pos_01", "topic": "T", "kind": "positive", "outcome": "completed",
             "latency_seconds": 275.0, "valid_claims": 1, "artifact": None,
             "dataset_entry": {"expected_themes": ["Molecular representation"], "max_results": 2}},
            {"topic_id": "neg_01", "topic": "N", "kind": "negative_control", "outcome": "completed",
             "latency_seconds": 5.0, "valid_claims": 0, "artifact": None, "dataset_entry": {}},
        ]
        artifacts = [
            {"status": _STATUS, "result": _CLEAN},
            {"status": {}, "result": {"papers": [], "claims": []}},
        ]
        computed = compute_metrics(run_records, artifacts)
        markdown = render_markdown(Path(tempfile.gettempdir()), run_records, computed)
        return (
            "Tóm tắt điều hành" in markdown
            and "Trích dẫn bịa" in markdown
            and "🟢 đạt" in markdown          # negative control passes
            and "chưa đo" in markdown          # honest about cost/baseline
        )

    cases.append((
        "Báo cáo dựng được từ đầu tới cuối, có cả mục 'chưa đo'",
        _report_renders,
        "báo cáo phải nói rõ cái gì chưa đo, thay vì để trống cho người đọc tự suy diễn",
    ))

    def _unsupported_domain_is_audited_not_scored() -> bool:
        core = {
            "topic_id": "pos_core", "topic": "Core", "kind": "positive", "outcome": "completed",
            "latency_seconds": 10.0, "valid_claims": 1,
            "dataset_entry": {"expected_themes": [], "max_results": 2},
        }
        unsupported = {
            "topic_id": "pos_bio", "topic": "Biomedical", "kind": "positive", "outcome": "failed",
            "error": "no corpus", "dataset_entry": {
                "evaluation_scope": "unsupported_domain", "scope_reason": "no biomedical corpus",
            },
        }
        computed = compute_metrics([core, unsupported], [{"status": _STATUS, "result": _CLEAN}, {"status": {}, "result": {}}])
        return (
            computed["metrics"]["Tỷ lệ chạy thành công"].value == 1.0
            and computed["failure_taxonomy"] == []
            and computed["unsupported_domain_runs"][0]["topic_id"] == "pos_bio"
        )

    cases.append((
        "Domain chưa hỗ trợ được audit riêng, không kéo tụt score core",
        _unsupported_domain_is_audited_not_scored,
        "benchmark core không được đánh đồng thiếu corpus domain với lỗi workflow trong scope",
    ))

    # --- refusal_kind phân loại đúng ----------------------------------------
    # Kiểm tra logic mới trong runner: completed+rỗng → intentional_refusal;
    # error+crash message → infrastructure_error.  Dùng trực tiếp các constant
    # từ runner module để test đảm bảo chính xác cùng ngưỡng.
    from benchmarks.runner import _INTENTIONAL_REFUSAL_SIGNALS

    def _classify_refusal(error: str | None, errored: bool) -> str:
        """Mirror of the classification logic in runner.run_one()."""
        error_lower = (error or "").lower()
        is_intentional = (
            not errored
            or any(sig in error_lower for sig in _INTENTIONAL_REFUSAL_SIGNALS)
        )
        return "intentional_refusal" if is_intentional else "infrastructure_error"

    cases.append((
        "Negative control: completed+rỗng → intentional_refusal",
        lambda: _classify_refusal(None, errored=False) == "intentional_refusal",
        "API hoàn tất sạch mà không có output = từ chối có chủ đích (out_of_scope path)",
    ))
    cases.append((
        "Negative control: error+crash message → infrastructure_error",
        lambda: _classify_refusal("ConnectionError: DB pool exhausted", errored=True) == "infrastructure_error",
        "lỗi hạ tầng không nên được tính là pass cho negative control",
    ))
    cases.append((
        "Negative control: error+refusal keyword → intentional_refusal",
        lambda: _classify_refusal("ValueError: no relevant papers found for topic", errored=True) == "intentional_refusal",
        "pipeline bị lỗi vì từ chối — vẫn là từ chối có chủ đích",
    ))
    cases.append((
        "Negative control: câu từ chối thực tế tiếng Việt → intentional_refusal",
        lambda: _classify_refusal(
            "Không có bài báo nào phù hợp để tổng hợp cho truy vấn này. Hệ thống sẽ không bịa thêm nguồn.",
            errored=True,
        ) == "intentional_refusal",
        "câu từ chối API thực tế phải không bị ghi nhầm là lỗi hạ tầng",
    ))

    from benchmarks.__main__ import _expected_counts
    from benchmarks.runner import RunRecord

    cases.append((
        "CLI chỉ tính completed và intentional_refusal là đúng kỳ vọng",
        lambda: _expected_counts([
            RunRecord("pos", "P", "positive", 1, outcome="completed"),
            RunRecord("neg_ok", "N", "negative_control", 1, outcome="refused", refusal_kind="intentional_refusal"),
            RunRecord("neg_crash", "N", "negative_control", 1, outcome="refused", refusal_kind="infrastructure_error"),
        ]) == (2, 1),
        "một crash trả rỗng không được làm CLI và CI xanh giả",
    ))

    # --- negative control: lỗi hạ tầng không được tính pass -------------------
    # Hồi quy cho bug thật: runner phân loại đúng infrastructure_error, nhưng
    # metric cũ chỉ nhìn "output rỗng" nên vẫn chấm pass — headline "Kiểm soát
    # âm 100%" có thể chứa lượt crash, mâu thuẫn với dòng cảnh báo của chính
    # báo cáo.
    cases.append((
        "Kiểm soát âm: output rỗng do LỖI HẠ TẦNG → KHÔNG tính đạt",
        lambda: trust.negative_control(
            papers=0, valid_claims=0, refusal_kind="infrastructure_error",
        ).value == 0.0,
        "DB crash mà output tình cờ rỗng không chứng minh hệ thống trung thực",
    ))
    cases.append((
        "Kiểm soát âm: từ chối có chủ đích → đạt",
        lambda: trust.negative_control(
            papers=0, valid_claims=0, refusal_kind="intentional_refusal",
        ).value == 1.0,
        "hoàn tất sạch với output rỗng hoặc lỗi-kèm-từ-khóa là hành vi đúng",
    ))

    # --- verify-sources: chứng minh corpus là thật ---------------------------
    from benchmarks.external import source_check

    async def _source_errors_are_persisted() -> bool:
        original_resolver = source_check.resolve_paper

        async def _unresolved(*_args: Any, **_kwargs: Any) -> None:
            return None

        source_check.resolve_paper = _unresolved
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                run_dir = Path(temp_dir)
                artifact_name = "pos_01_attempt1.json"
                (run_dir / artifact_name).write_text(
                    json.dumps({"result": {"papers": [{"paper_id": "W1"}]}}), encoding="utf-8",
                )
                runs = [{"topic_id": "pos_01", "outcome": "completed", "artifact": artifact_name}]
                filled, _reason = await source_check.backfill_run_dir(run_dir, runs)
                persisted = json.loads((run_dir / "runs.json").read_text(encoding="utf-8"))
                return (
                    filled == 0
                    and persisted[0]["source_check"]["resolved"] == 0
                    and len(persisted[0]["source_check"]["errors"]) == 1
                )
        finally:
            source_check.resolve_paper = original_resolver

    cases.append((
        "Source check: toàn bộ resolver lỗi vẫn được persist vào runs.json",
        lambda: asyncio.run(_source_errors_are_persisted()),
        "mất diagnostics khi provider lỗi sẽ biến 'chưa đo' thành không thể kiểm toán",
    ))

    cases.append((
        "Resolver tách đúng nhà cung cấp theo tiền tố paper_id",
        lambda: (
            source_check.endpoint_for("W3110901318")[0] == "openalex"
            and source_check.endpoint_for("s2:abc123")[0] == "semantic_scholar"
            and source_check.endpoint_for("doi:10.1/x")[0] == "openalex"
            and "id_list=2509.07887" in source_check.endpoint_for("arxiv:2509.07887v1")[1]
            and source_check.endpoint_for("unk:???") is None
        ),
        "tra ID arXiv lên OpenAlex sẽ 404 oan — mỗi nguồn phải tra đúng API của nó",
    ))
    checked_runs = [
        {"topic_id": "pos_01", "source_check": {"resolved": 2, "not_found": ["W999"], "errors": ["s2:x: ConnectError"]}},
        {"topic_id": "pos_02", "source_check": {"resolved": 1, "not_found": [], "errors": []}},
    ]
    cases.append((
        "Nguồn tra cứu được thật: tính từ kết quả đã lưu, loại lỗi kiểm tra khỏi mẫu số",
        lambda: (
            lambda m: m is not None and m.value == 3 / 4 and m.denominator == 4
        )(trust.source_resolvability(checked_runs)),
        "lỗi mạng phía kiểm tra không được quy oan là nguồn bịa của sản phẩm",
    ))
    cases.append((
        "Nguồn tra cứu được thật: verify-sources chưa chạy → metric vắng mặt",
        lambda: trust.source_resolvability([{"topic_id": "pos_01"}]) is None,
        "run dir cũ không có source_check thì không hiện 'chưa đo' hàng loạt",
    ))
    cases.append((
        "Nguồn tra cứu được thật: tra không được paper nào → chưa đo, kèm lý do",
        lambda: (lambda m: m is not None and not m.measured and "lỗi" in (m.unmeasured_reason or ""))(
            trust.source_resolvability([{"topic_id": "pos_01", "source_check": {"resolved": 0, "not_found": [], "errors": ["W1: 429"]}}]),
        ),
        "0/0 là chưa đo — in ra tỷ lệ 0% ở đây là bịa kết quả xấu nhất cho sản phẩm",
    ))

    # --- bottleneck aggregation đúng -----------------------------------------
    # Hai lượt với bottleneck ratio khác nhau phải cho mean, KHÔNG phải
    # sum(seconds) / sum(seconds).  Nếu sai, aggregation sẽ trả giá trị lệch.
    def _bottleneck_aggregates_correctly() -> bool:
        status_a = {
            "node_trace": [
                {"node": "queued",    "created_at": "2026-08-20T10:00:00+00:00"},
                {"node": "search",    "created_at": "2026-08-20T10:00:10+00:00"},  # 10s
                {"node": "synthesis", "created_at": "2026-08-20T10:00:20+00:00"},  # 10s → 50%
            ],
        }
        status_b = {
            "node_trace": [
                {"node": "queued",    "created_at": "2026-08-20T11:00:00+00:00"},
                {"node": "search",    "created_at": "2026-08-20T11:00:05+00:00"},  # 5s
                {"node": "synthesis", "created_at": "2026-08-20T11:00:25+00:00"},  # 20s → 80%
            ],
        }
        m_a = performance.bottleneck(status_a)
        m_b = performance.bottleneck(status_b)
        assert m_a.measured and m_b.measured, "fixture must produce measured results"

        # Aggregate via _mean_metric (same path as report.py)
        from benchmarks.report import _mean_metric
        agg = _mean_metric("Nút thắt cổ chai", [m_a, m_b])
        if not agg.measured:
            return False
        # Expected: mean(0.5, 0.8) = 0.65, NOT sum(10,20)/sum(20,25) = 30/45 = 0.67
        expected_mean = (m_a.value + m_b.value) / 2  # type: ignore[operator]
        assert agg.value is not None
        return abs(agg.value - expected_mean) < 1e-9

    cases.append((
        "Bottleneck aggregated qua nhiều lượt dùng mean(ratio), không phải sum(seconds)/sum(seconds)",
        _bottleneck_aggregates_correctly,
        "sum seconds qua lượt khác nhau là vô nghĩa — phải mean của ratio mỗi lượt",
    ))

    return cases


def run_selftest() -> int:
    cases = _cases()
    failed: list[str] = []
    print(f"Kiểm tra bộ đo — {len(cases)} phép thử (offline, không cần API/DB)\n")
    for name, check, why in cases:
        try:
            ok = bool(check())
        except Exception as exc:
            ok = False
            why = f"{why} [lỗi: {type(exc).__name__}: {exc}]"
        print(f"  {'✅' if ok else '❌'} {name}")
        if not ok:
            failed.append(f"{name} — {why}")
    print()
    if failed:
        print(f"❌ {len(failed)}/{len(cases)} phép thử TRƯỢT:")
        for item in failed:
            print(f"   · {item}")
        return 1
    print(f"✅ {len(cases)}/{len(cases)} đạt — bộ đo tin dùng được.")
    return 0
