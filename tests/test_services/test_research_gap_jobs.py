from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.agents import research_gap_graph
from src.services import research_gap_jobs


def _papers() -> list[dict]:
    return [
        {
            "paper_id": f"W{i}",
            "title": f"Retrieval systems study {i}",
            "authors": ["Author"],
            "year": 2024,
            "doi": None,
            "url": f"https://example.org/W{i}",
            "abstract": "This retrieval systems study evaluates accuracy in English benchmarks.",
            "cited_by_count": 10,
            "is_open_access": True,
            "source": "openalex",
        }
        for i in range(10)
    ]


class FakeRepository:
    def __init__(self) -> None:
        self.result: dict | None = None
        self.status = "queued"
        self.nodes: list[str] = []

    def update_progress(self, _job_id, node, **_kwargs) -> None:
        self.status = "running"
        self.nodes.append(node)

    def complete_job(self, _job_id, result: dict) -> None:
        self.result = result

    def finalize_job(self, _job_id, _result: dict) -> None:
        self.status = "approved"


@pytest.mark.asyncio
async def test_gap_detector_requests_vietnamese_user_facing_copy() -> None:
    seen: list[str] = []

    async def invoke(_schema, messages):
        seen.append(str(messages[0].content))
        return research_gap_graph.DetectorResult()

    async def countersearch(_candidates):
        return {}

    graph = research_gap_graph.ResearchGapGraph(invoke, countersearch)
    await graph.topical_detector(
        {
            "topic": "RAG cho tiếng Việt",
            "language": "Vietnamese",
            "papers": _papers()[:1],
            "extracted": {},
        }
    )

    assert "natural Vietnamese" in seen[0]
    assert "evidence_quote verbatim" in seen[0]
    assert "supplied source passage" in seen[0]


@pytest.mark.asyncio
async def test_gap_corpus_applies_required_scope_terms(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class FakeSearch:
        async def search_all_sources(self, _topic, _limit):
            return _papers(), []

        async def snowball(self, _papers, max_results=10):
            return [], []

        async def close(self):
            return None

    def fake_rank(papers, _queries, limit, **kwargs):
        observed.update(kwargs)
        return papers[:limit]

    monkeypatch.setattr(research_gap_jobs, "AcademicSearchService", FakeSearch)
    monkeypatch.setattr(research_gap_jobs, "rank_papers", fake_rank)
    plan = research_gap_graph.GapQuery(
        core_topic="RAG for multi-hop question answering",
        facets=["iterative retrieval for multi-hop QA"],
        required_terms=["RAG"],
    )

    await research_gap_jobs.ResearchGapJobService(FakeRepository())._build_corpus("topic", plan, 15)

    assert observed["required_terms"] == ["RAG"]


@pytest.mark.asyncio
async def test_gap_job_runs_cold_start_and_independent_graph(monkeypatch) -> None:
    class FakeSearch:
        async def search_all_sources(self, _topic, _limit):
            return _papers(), []

        async def snowball(self, _papers, max_results=10):
            return [], []

        async def close(self):
            return None

    quote = "This retrieval systems study evaluates accuracy in English benchmarks."
    candidate = research_gap_graph.GapCandidate(
        aspect="Vietnamese-language evaluation benchmark",
        statement="The retrieved corpus does not provide a Vietnamese-language evaluation benchmark.",
        evidence=[
            research_gap_graph.CandidateEvidence(paper_id="W0", evidence_quote=quote),
            research_gap_graph.CandidateEvidence(paper_id="W1", evidence_quote=quote),
        ],
        counter_search_query="Vietnamese RAG factuality evaluation benchmark",
        reviewer_rationale="The retrieved evidence evaluates English benchmarks.",
        suggested_method="Build a Vietnamese benchmark and compare it with English baselines.",
        falsification_condition="A directly comparable Vietnamese benchmark study is retrieved.",
    )

    class FakeChain:
        def __init__(self, schema):
            self.schema = schema

        async def ainvoke(self, _messages):
            if self.schema is research_gap_graph.GapQuery:
                return research_gap_graph.GapQuery(core_topic="RAG factuality", facets=["Vietnamese RAG benchmark"])
            if self.schema is research_gap_jobs.HyDEQuery:
                return research_gap_jobs.HyDEQuery(
                    hypothetical_document="A study evaluating Vietnamese RAG factuality benchmarks and methods."
                )
            if self.schema is research_gap_graph.ExtractionResult:
                return research_gap_graph.ExtractionResult(
                    papers=[research_gap_graph.ExtractedPaper(paper_id=f"W{i}") for i in range(10)]
                )
            if self.schema is research_gap_graph.DetectorResult:
                return research_gap_graph.DetectorResult(candidates=[candidate])
            if self.schema is research_gap_graph.OriginResult:
                return research_gap_graph.OriginResult(
                    origins=[
                        research_gap_graph.OriginAssessment(
                            index=index, origin="inferred", rationale="Corpus coverage inference."
                        )
                        for index in range(3)
                    ]
                )
            if self.schema is research_gap_graph.VerificationResult:
                return research_gap_graph.VerificationResult(
                    assessments=[
                        research_gap_graph.VerificationAssessment(
                            index=index,
                            verdict="supported",
                            rationale="Evidence supports the corpus-scoped statement.",
                            subclaims=[
                                research_gap_graph.AtomicAssessment(
                                    statement="The retrieved corpus does not contain a Vietnamese-language benchmark.",
                                    verdict="supported",
                                )
                            ],
                        )
                        for index in range(3)
                    ]
                )
            if self.schema is research_gap_graph.CounterAssessmentResult:
                return research_gap_graph.CounterAssessmentResult()
            raise AssertionError(f"Unexpected schema {self.schema}")

    class FakeModel:
        native_schema_supported = True

        def with_structured_output(self, schema):
            return FakeChain(schema)

    monkeypatch.setattr(research_gap_jobs, "AcademicSearchService", FakeSearch)
    monkeypatch.setattr(research_gap_jobs, "get_llm", lambda: FakeModel())
    monkeypatch.setattr(research_gap_jobs, "get_settings", lambda: SimpleNamespace(qdrant_enabled=False))
    repository = FakeRepository()

    await research_gap_jobs.ResearchGapJobService(repository).run(
        "gap-job",
        {"original_topic": "Vietnamese RAG factuality", "max_results": 15, "workflow_type": "research_gap"},
    )

    assert repository.result is not None
    assert repository.status == "approved"
    assert repository.result["intent"] == "research_gap"
    assert repository.result["papers_count"] == 10
    assert len(repository.result["potential_gaps"]) == 1
    gap = repository.result["potential_gaps"][0]
    assert gap["origin"] == "inferred"
    assert gap["verification_verdict"] == "supported"
    assert gap["quality_score"] >= 0
    assert gap["countersearch_performed"] is True
    assert {
        "query_shaping",
        "gap_search",
        "gap_extraction",
        "extract",
        "topical_detector",
        "method_detector",
        "contradiction_detector",
        "origin_labeling",
        "verifier",
        "counter_evidence",
        "quality_scoring",
        "deduplicate",
        "synthesize",
    } <= set(repository.nodes)
