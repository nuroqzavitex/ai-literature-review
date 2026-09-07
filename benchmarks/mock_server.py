"""Mock server — CHỈ dùng để kiểm tra bộ đo, KHÔNG thay thế chạy thật.

⚠️  WARNING: SỐ TỪ MOCK KHÔNG CÓ GIÁ TRỊ ĐO LƯỜNG GÌ CẢ.
    Mock trả artifact cố định — mọi metric đều "đạt" theo thiết kế vì
    dữ liệu do chính bộ đo kiểm soát. Đây là kiểm tra tự thân (sanity
    check) của framework, không phải benchmark sản phẩm.

    Dùng đúng: CI không có API key (chỉ cần biết runner + report không crash)
    Dùng SAI:  lấy số từ mock để báo cáo chất lượng sản phẩm

Để chạy benchmark thật:
    docker compose up -d backend worker   # khởi động stack
    python -m benchmarks selftest         # kiểm tra bộ đo trước
    python -m benchmarks run              # chạy với API thật ở localhost:8000

Giả lập đúng 4 endpoint mà runner gọi:
  GET  /api/v1/health
  POST /api/v1/reviews
  GET  /api/v1/reviews/{job_id}/status
  GET  /api/v1/reviews/{job_id}
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

# ---------------------------------------------------------------------------
# Dữ liệu mẫu — đủ để tất cả metric đều có thứ để đo
# ---------------------------------------------------------------------------

# Abstract thật của 3 paper để quote có thể khớp nguyên văn (verbatim check).
_PAPERS: list[dict[str, Any]] = [
    {
        "paper_id": "W2000001",
        "title": "GraphDTA: Predicting drug-target binding affinity with graph neural networks",
        "authors": [{"name": "Nguyen et al."}],
        "year": 2021,
        "abstract": (
            "Predicting drug-target binding affinity is a challenging problem in drug discovery. "
            "We propose GraphDTA, a method that uses graph neural networks to represent drugs "
            "as molecular graphs and predict binding affinity with target proteins. "
            "GraphDTA achieves state-of-the-art results on the Davis and KIBA benchmark datasets."
        ),
        "doi": "10.1093/bioinformatics/btaa921",
        "venue": "Bioinformatics",
        "citation_count": 850,
    },
    {
        "paper_id": "W2000002",
        "title": "A comprehensive survey of graph neural networks for molecular property prediction",
        "authors": [{"name": "Zhang et al."}],
        "year": 2022,
        "abstract": (
            "Graph neural networks have emerged as the dominant paradigm for molecular representation learning. "
            "This survey covers message-passing frameworks, attention-based pooling, and their applications "
            "to property prediction and molecular generation in drug discovery pipelines."
        ),
        "doi": "10.1021/acs.chemrev.1c00107",
        "venue": "Chemical Reviews",
        "citation_count": 1200,
    },
    {
        "paper_id": "W2000003",
        "title": "MolBERT: molecular BERT for generative molecular design",
        "authors": [{"name": "Fabian et al."}],
        "year": 2020,
        "abstract": (
            "We introduce MolBERT, a transformer-based model pre-trained on molecular SMILES strings "
            "for generative molecular design and property prediction. "
            "Pre-training on 1.6 million molecules enables few-shot transfer to downstream tasks."
        ),
        "doi": "10.26434/chemrxiv.12820303",
        "venue": "ChemRxiv",
        "citation_count": 420,
    },
]

_REFERENCES: list[dict[str, Any]] = [
    {"paper_id": p["paper_id"], "title": p["title"], "doi": p.get("doi")}
    for p in _PAPERS
]

# Claim + evidence: quote khớp nguyên văn một đoạn trong abstract ở trên.
_CLAIMS: list[dict[str, Any]] = [
    {
        "claim_id": "c1",
        "claim_type": "contribution",
        "validation_status": "valid",
        "text": (
            "GraphDTA dùng graph neural network để biểu diễn thuốc dưới dạng đồ thị phân tử "
            "và đạt kết quả tốt nhất trên Davis và KIBA."
        ),
        "supporting_paper_ids": ["W2000001"],
        "evidence": [
            {
                "paper_id": "W2000001",
                "quote": (
                    "GraphDTA achieves state-of-the-art results on the Davis and KIBA benchmark datasets."
                ),
                "source_level": "abstract",
            }
        ],
    },
    {
        "claim_id": "c2",
        "claim_type": "contribution",
        "validation_status": "valid",
        "text": (
            "GNN trở thành paradigm chủ đạo cho molecular representation learning, "
            "bao gồm message-passing, attention pooling và sinh phân tử."
        ),
        "supporting_paper_ids": ["W2000002"],
        "evidence": [
            {
                "paper_id": "W2000002",
                "quote": (
                    "Graph neural networks have emerged as the dominant paradigm for molecular representation learning."
                ),
                "source_level": "abstract",
            }
        ],
    },
    {
        "claim_id": "c3",
        "claim_type": "contribution",
        "validation_status": "valid",
        "text": "MolBERT tiền huấn luyện trên 1,6 triệu phân tử cho khả năng few-shot transfer tốt.",
        "supporting_paper_ids": ["W2000003"],
        "evidence": [
            {
                "paper_id": "W2000003",
                "quote": (
                    "Pre-training on 1.6 million molecules enables few-shot transfer to downstream tasks."
                ),
                "source_level": "abstract",
            }
        ],
    },
    {
        "claim_id": "c4",
        "claim_type": "potential_gap",
        "validation_status": "valid",
        "text": "Các bài được khảo sát chưa đánh giá trên tập dữ liệu lâm sàng thực tế.",
        "supporting_paper_ids": ["W2000001", "W2000002"],
        "evidence": [],
    },
]

_LITERATURE_REVIEW: dict[str, Any] = {
    "title": "Graph Neural Networks in Drug Discovery: A Systematic Review",
    "abstract": (
        "This review synthesises recent advances in graph neural network (GNN) methods "
        "applied to drug discovery, covering molecular property prediction, binding affinity "
        "estimation, and generative molecular design."
    ),
    "introduction": (
        "Drug discovery is a costly and time-consuming process. GNNs offer a principled way "
        "to encode molecular structure as graphs, enabling better generalisation than fingerprint-based baselines."
    ),
    "sections": [
        {
            "title": "Molecular Representation",
            "paragraphs": [
                "Atoms and bonds form a natural graph; GNNs propagate information through "
                "message-passing layers to learn atom embeddings aware of local chemical context.",
                "GraphDTA extends this to drug-target affinity prediction, achieving competitive results.",
            ],
        },
        {
            "title": "Property Prediction",
            "paragraphs": [
                "Benchmark comparisons on Davis and KIBA show that graph-level pooling strategies "
                "(mean, sum, attention) markedly affect downstream accuracy.",
            ],
        },
        {
            "title": "Generative Models",
            "paragraphs": [
                "MolBERT and junction-tree VAE represent two design philosophies: sequence-level "
                "pre-training vs. explicit graph generation with validity guarantees.",
            ],
        },
    ],
    "conclusion": (
        "GNNs are now a core tool in computational drug discovery. Future work should address "
        "scalability to ultra-large chemical libraries and interpretability of learned representations."
    ),
    "limitations": (
        "This review is limited to English-language publications indexed on Semantic Scholar "
        "and may miss domain-specific conference proceedings."
    ),
}


def _node_trace() -> list[dict[str, Any]]:
    return [
        {"node": "queued",                  "created_at": "2026-08-22T00:00:00+00:00", "papers_found": 0},
        {"node": "search_academic_sources", "created_at": "2026-08-22T00:00:15+00:00", "papers_found": 38},
        {"node": "screen_papers",           "created_at": "2026-08-22T00:00:30+00:00", "papers_found": len(_PAPERS)},
        {"node": "extract_evidence",        "created_at": "2026-08-22T00:04:30+00:00", "papers_found": len(_PAPERS)},
        {"node": "synthesise_review",       "created_at": "2026-08-22T00:05:00+00:00", "papers_found": len(_PAPERS)},
    ]


def _make_positive_result() -> dict[str, Any]:
    """Phần result trả thẳng từ GET /reviews/{job_id} — đúng với dạng API thật.

    Runner gán ``result = fetched.json()`` rồi đọc ``result.get("papers")``,
    nên endpoint này KHÔNG được wrap thêm {"result": ...}.
    Artifact lưu xuống đĩa ({"status":…, "result":…}) được runner tự dựng sau.
    """
    return {
        "papers": _PAPERS,
        "references": _REFERENCES,
        "themes": [
            {"title": "Molecular representation", "summary_claim_id": "c1"},
            {"title": "Property prediction",       "summary_claim_id": "c2"},
            {"title": "Generative models",         "summary_claim_id": "c3"},
        ],
        "claims": _CLAIMS,
        "literature_review": _LITERATURE_REVIEW,
    }


def _make_negative_result() -> dict[str, Any]:
    return {"papers": [], "references": [], "themes": [], "claims": [], "literature_review": {}}


# ---------------------------------------------------------------------------
# Job store — in-memory, thread-safe
# ---------------------------------------------------------------------------

class _JobStore:
    def __init__(self, latency: float, fail_rate: float) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._latency = latency
        self._fail_rate = fail_rate

    def create(self, topic: str, kind: str) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "topic": topic,
                "kind": kind,
                "ready_at": time.monotonic() + self._latency,
                "will_fail": random.random() < self._fail_rate,
            }
        return job_id

    def status(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        if time.monotonic() < job["ready_at"]:
            return {"status": "processing", "current_node": "extract_evidence"}
        if job["will_fail"]:
            return {"status": "error", "error": "SimulatedError: mock fail_rate triggered"}
        is_neg = job["kind"] == "negative_control"
        return {"status": "completed", "papers": [] if is_neg else _PAPERS}

    def artifact(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job["will_fail"]:
            return None
        if job["kind"] == "negative_control":
            return _make_negative_result()
        return _make_positive_result()


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

_store: _JobStore  # set at startup


class _Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt: str, *args: Any) -> None:  # type: ignore[override]
        print(f"  {self.command} {self.path} → {args[1] if len(args) > 1 else ''}")

    def _send_json(self, code: int, body: Any) -> None:
        payload = json.dumps(body, ensure_ascii=False, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_404(self) -> None:
        self._send_json(404, {"detail": "not found"})

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")

        if path == "/api/v1/health":
            self._send_json(200, {"status": "ok", "mock": True})
            return

        if path.startswith("/api/v1/reviews/") and path.endswith("/status"):
            job_id = path[len("/api/v1/reviews/"):-len("/status")]
            status = _store.status(job_id)
            if status is None:
                self._send_404()
            else:
                self._send_json(200, status)
            return

        if path.startswith("/api/v1/reviews/"):
            job_id = path[len("/api/v1/reviews/"):]
            artifact = _store.artifact(job_id)
            if artifact is None:
                self._send_404()
            else:
                self._send_json(200, artifact)
            return

        self._send_404()

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")

        if path == "/api/v1/reviews":
            body = self._read_body()
            topic = str(body.get("topic", "unknown"))
            kind = "negative_control" if _is_negative_topic(topic) else "positive"
            job_id = _store.create(topic, kind)
            self._send_json(201, {"job_id": job_id})
            return

        self._send_404()


def _is_negative_topic(topic: str) -> bool:
    """Heuristic nhận biết negative_control topic từ topics.json."""
    lowered = topic.lower()
    signals = [
        "xyzqwerty",
        "quantum blockchain telepathy",
        "photosynthetic compilers",
        "fakeconlang quark taxonomy",
        "neverpublished protocol",
        "99999",
    ]
    return any(s in lowered for s in signals)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Mock server để chạy benchmark offline.\n"
            "Sau khi khởi động:\n"
            "  python -m benchmarks run --base-url http://localhost:<port>/api/v1"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--port",      type=int,   default=9876,
                   help="Cổng lắng nghe (mặc định 9876)")
    p.add_argument("--latency",   type=float, default=0.5,
                   help="Giây giả lập thời gian xử lý mỗi job (mặc định 0.5)")
    p.add_argument("--fail-rate", type=float, default=0.0,
                   help="Xác suất [0‒1] mỗi job bị error — để đo reliability (mặc định 0)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    global _store
    _store = _JobStore(latency=args.latency, fail_rate=args.fail_rate)

    server = HTTPServer(("localhost", args.port), _Handler)
    base = f"http://localhost:{args.port}/api/v1"
    print(f"🟢 Mock server sẵn sàng tại {base}")
    print(f"   latency={args.latency}s  fail_rate={args.fail_rate:.0%}")
    print()
    print("Chạy benchmark:")
    print(f"  python -m benchmarks run --base-url {base}")
    print(f"  python -m benchmarks run --base-url {base} --only pos_01,neg_01")
    print()
    print("Dừng server: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⛔ Dừng mock server.")


if __name__ == "__main__":
    main()
