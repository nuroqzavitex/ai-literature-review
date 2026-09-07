import httpx
import pytest

from src.agents.litreview.domain.models import AgentState, Paper
from src.agents.litreview.workflow.nodes import (
    _compact_sub_query,
    _explicit_publication_year_range,
    extract_evidence_node,
    human_review_node,
    intent_guardrail_node,
    out_of_scope_node,
    plan_search_node,
    screen_papers_node,
    search_academic_sources_node,
    synthesize_claims_node,
    validate_grounding_node,
)
from src.services.academic_search import AcademicSearchService, rank_papers


def paper(
    paper_id: str,
    title: str,
    abstract: str,
    *,
    year: int = 2024,
    citations: int = 0,
) -> Paper:
    return {
        "paper_id": paper_id,
        "title": title,
        "authors": ["Ada Researcher", "Bao Reviewer"],
        "year": year,
        "doi": None,
        "url": f"https://openalex.org/{paper_id}",
        "abstract": abstract,
        "cited_by_count": citations,
        "is_open_access": True,
    }


def test_rank_papers_prefers_topic_overlap():
    papers = [
        paper("1", "Marine biology survey", "We study coral reefs.", citations=100),
        paper(
            "2",
            "Graph neural networks for drug discovery",
            "A graph neural network predicts molecular properties.",
        ),
    ]
    ranked = rank_papers(papers, "graph neural networks drug discovery", limit=2)
    assert ranked[0]["paper_id"] == "2"
    assert ranked[0]["rank"] == 1
    assert 0 <= ranked[0]["relevance_score"] <= 1


def test_compact_sub_query_limits_length_to_fourteen_terms():
    query = "How does artificial intelligence improve emergency department triage accuracy speed fairness external validation and real world clinical deployment outcomes"

    compact = _compact_sub_query(query)

    assert len(compact.split()) == 14
    assert not compact.lower().startswith("how does")


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_mode", ["review", "autonomous"])
async def test_final_review_is_approved_automatically(execution_mode):
    result = await human_review_node({"execution_mode": execution_mode, "decisions": []})

    assert result["status"] == "running"
    assert result["hitl_decision"] == "approve"
    assert result["hitl_payload"] is None
    assert result["current_node"] == "finalize"
    assert result["decisions"][-1]["action"] == "continue"


def test_sub_query_plan_rejects_queries_outside_eight_to_fourteen_words():
    from pydantic import ValidationError

    from src.agents.litreview.prompts.query_planning import SubQueryPlan

    with pytest.raises(ValidationError, match="8-14 words"):
        SubQueryPlan(
            normalized_question="Effects of AI feedback on learning",
            sub_queries=["AI feedback learning outcomes"],
        )


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("AI triage từ năm 2018", (2018, None)),
        ("AI triage trước năm 2018", (None, 2017)),
        ("AI triage in 2018–2024", (2018, 2024)),
        ("AI triage without a publication constraint", None),
    ],
)
def test_explicit_publication_year_range(topic, expected):
    assert _explicit_publication_year_range(topic) == expected


def test_rank_papers_rejects_one_word_semantic_drift():
    ranked = rank_papers(
        [
            paper(
                "W-teleport",
                "Quantum teleportation in communication networks",
                "We evaluate entanglement-assisted quantum teleportation protocols for networks.",
            )
        ],
        "Quantum Telepathy",
        limit=10,
    )

    assert ranked == []


def test_rank_papers_scores_each_subquery_independently():
    papers = [
        paper("1", "Amniote egg evolution", "The evolutionary origin of the amniote egg.", citations=5),
        paper("2", "Chicken domestication phylogeny", "Phylogenetic history of domestic chickens.", citations=5),
        paper("3", "Egg nutrition review", "Nutritional composition of chicken eggs.", citations=500),
    ]
    ranked = rank_papers(
        papers,
        ["amniote egg evolutionary origin", "chicken domestication phylogeny"],
        limit=3,
    )

    assert [item["paper_id"] for item in ranked] == ["1", "2"]


def test_rank_papers_enforces_required_and_excluded_intent_terms():
    papers = [
        paper("1", "Evolution of the amniote egg", "Evolutionary origin of the amniote egg.", citations=2),
        paper("2", "Egg nutrition review", "Nutritional composition and cholesterol in eggs.", citations=500),
    ]

    ranked = rank_papers(
        papers,
        ["egg evolutionary origin"],
        limit=2,
        required_terms=["amniote egg", "evolutionary origin"],
        excluded_terms=["egg nutrition"],
    )

    assert [item["paper_id"] for item in ranked] == ["1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_mode", ["review", "autonomous"])
async def test_screen_papers_requires_embedding_score_of_point_six(monkeypatch, execution_mode):
    from src.agents.litreview.prompts.relevance import PaperRelevanceBatch, PaperRelevanceDecision
    from src.agents.litreview.workflow import nodes as litreview

    class FakeStore:
        def __init__(self, *, backend="primary"):
            self.collection = f"test_{backend}"

        async def index_and_rank(self, papers, _query, _job_id, _limit):
            scores = {"W1": 0.80, "W2": 0.70, "W3": 0.61, "W4": 0.59}
            return [
                {**item, "relevance_score": scores[item["paper_id"]], "rank": index + 1}
                for index, item in enumerate(papers)
            ]

    class FakeJudge:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs):
            return PaperRelevanceBatch(
                decisions=[
                    PaperRelevanceDecision(paper_id="W1", label="direct", reason="Direct evidence."),
                    PaperRelevanceDecision(paper_id="W2", label="direct", reason="Direct evidence."),
                    PaperRelevanceDecision(paper_id="W3", label="supporting", reason="Necessary context."),
                ]
            )

    class Settings:
        qdrant_enabled = True
        qdrant_embedding_candidate_limit = 30
        qdrant_fallback_enabled = True

    monkeypatch.setattr(litreview, "QdrantVectorStore", FakeStore)
    monkeypatch.setattr(litreview, "get_settings", lambda: Settings())
    monkeypatch.setattr(litreview, "_StructuredLLMInvoker", FakeJudge)
    state = AgentState(
        job_id="job-semantic-gate",
        execution_mode=execution_mode,
        original_topic="amniote egg evolutionary origin",
        sub_queries=["amniote egg evolutionary origin"],
        papers=[
            paper("W1", "Evolution of the amniote egg", "The evolutionary origin of the amniote egg."),
            paper("W2", "Amniote egg origins", "Evolutionary origin of the amniote egg in vertebrates."),
            paper(
                "W3",
                "Oviparity evolution",
                "Oviparity supplies evidence about the evolutionary origin of the amniote egg.",
            ),
            paper("W4", "Weak amniote egg origin study", "A weak study of amniote egg evolutionary origin."),
        ],
        max_results=10,
    )

    result = await screen_papers_node(state)

    assert [item["paper_id"] for item in result["papers"]] == ["W1", "W2", "W3"]
    assert all(item["relevance_score"] >= 0.6 for item in result["papers"])
    assert result["hitl_stage"] == (None if execution_mode == "autonomous" else "papers")


@pytest.mark.asyncio
async def test_screen_papers_stops_when_direct_coverage_is_insufficient(monkeypatch):
    from src.agents.litreview.prompts.relevance import PaperRelevanceBatch, PaperRelevanceDecision
    from src.agents.litreview.workflow import nodes as litreview

    candidates = [
        paper("W1", "Amniote egg evolution one", "Evidence on amniote egg evolutionary origin."),
        paper("W2", "Amniote egg evolution two", "Context on amniote egg evolutionary origin."),
        paper("W3", "Amniote egg evolution three", "More context on amniote egg evolutionary origin."),
    ]

    class FakeStore:
        def __init__(self, *, backend="primary"):
            self.collection = f"test_{backend}"

        async def index_and_rank(self, papers, _query, _job_id, _limit):
            return [{**item, "relevance_score": 0.75, "rank": index + 1} for index, item in enumerate(papers)]

    class FakeJudge:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs):
            return PaperRelevanceBatch(
                decisions=[
                    PaperRelevanceDecision(paper_id="W1", label="direct", reason="Direct evidence."),
                    PaperRelevanceDecision(paper_id="W2", label="supporting", reason="Supporting context."),
                    PaperRelevanceDecision(paper_id="W3", label="background", reason="Only broad context."),
                ]
            )

    class Settings:
        qdrant_enabled = True
        qdrant_embedding_candidate_limit = 30
        qdrant_fallback_enabled = True

    monkeypatch.setattr(litreview, "QdrantVectorStore", FakeStore)
    monkeypatch.setattr(litreview, "get_settings", lambda: Settings())
    monkeypatch.setattr(litreview, "_StructuredLLMInvoker", FakeJudge)

    result = await screen_papers_node(
        AgentState(
            original_topic="amniote egg evolutionary origin",
            normalized_question="evolutionary origin of the amniote egg",
            sub_queries=["amniote egg evolutionary origin"],
            papers=candidates,
        )
    )

    assert result["papers"] == []
    assert any("INSUFFICIENT_DIRECT_COVERAGE" in warning for warning in result["source_warnings"])
    assert "Không có bài báo nào phù hợp để tổng hợp" in result["error"]


@pytest.mark.asyncio
async def test_screen_papers_falls_back_to_local_embedding_when_primary_fails(monkeypatch):
    from src.agents.litreview.prompts.relevance import PaperRelevanceBatch, PaperRelevanceDecision
    from src.agents.litreview.workflow import nodes as litreview
    from src.services.vector_store import VectorStoreError

    created_backends = []

    class FakeStore:
        def __init__(self, *, backend="primary"):
            self.backend = backend
            self.collection = f"papers_{backend}"
            created_backends.append(backend)

        async def index_and_rank(self, papers, _query, _job_id, _limit):
            if self.backend == "primary":
                raise VectorStoreError("429 quota exhausted")
            return [{**item, "relevance_score": 0.9, "rank": index + 1} for index, item in enumerate(papers)]

    class FakeJudge:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs):
            return PaperRelevanceBatch(
                decisions=[
                    PaperRelevanceDecision(paper_id="W1", label="direct", reason="Direct evidence."),
                    PaperRelevanceDecision(paper_id="W2", label="direct", reason="Direct evidence."),
                ]
            )

    class Settings:
        qdrant_enabled = True
        qdrant_embedding_candidate_limit = 30
        qdrant_fallback_enabled = True

    monkeypatch.setattr(litreview, "QdrantVectorStore", FakeStore)
    monkeypatch.setattr(litreview, "get_settings", lambda: Settings())
    monkeypatch.setattr(litreview, "_StructuredLLMInvoker", FakeJudge)

    result = await screen_papers_node(
        AgentState(
            job_id="job-local-fallback",
            execution_mode="autonomous",
            original_topic="amniote egg evolutionary origin",
            normalized_question="evolutionary origin of the amniote egg",
            sub_queries=["amniote egg evolutionary origin"],
            max_results=10,
            papers=[
                paper("W1", "Amniote egg evolution one", "Evidence on the evolutionary origin of the amniote egg."),
                paper(
                    "W2", "Amniote egg evolution two", "More evidence on the evolutionary origin of the amniote egg."
                ),
            ],
        )
    )

    assert created_backends == ["primary", "fallback"]
    assert result["embedding_backend"] == "fallback"
    assert result["embedding_collection"] == "papers_fallback"
    assert len(result["papers"]) == 2
    assert any("EMBEDDING_FALLBACK_USED" in warning for warning in result["source_warnings"])


def test_deduplicate_prefers_record_with_richer_abstract():
    short = paper("W001", "Same Paper", "Short abstract.")
    rich = {**short, "paper_id": "W002"}
    rich["abstract"] = "A much richer abstract with methods, data, and results."
    deduplicated = AcademicSearchService._deduplicate([short, rich])
    assert len(deduplicated) == 1
    assert deduplicated[0]["paper_id"] == "W002"


def test_deduplicate_prefers_published_version_over_preprint():
    preprint = {
        **paper("preprint", "Reciprocally-coupled Gating", "A detailed preprint abstract."),
        "doi": "10.20944/preprints202101.0057.v1",
        "url": "https://www.preprints.org/manuscript/202101.0057",
        "source": "openalex",
    }
    published = {
        **paper("published", "Reciprocally-Coupled Gating", "A shorter published abstract."),
        "doi": "10.3390/biom11020265",
        "url": "https://doi.org/10.3390/biom11020265",
        "source": "openalex",
    }

    deduplicated = AcademicSearchService._deduplicate([preprint, published])

    assert len(deduplicated) == 1
    assert deduplicated[0]["paper_id"] == "published"


def test_agent_contains_contract_nodes():
    from src.agents.litreview.workflow.graph import uncompiled_graph

    expected_nodes = {
        "intent_guardrail",
        "out_of_scope",
        "plan_search",
        "search_academic_sources",
        "assess_sources",
        "refine_query",
        "screen_papers",
        "extract_evidence",
        "synthesize_claims",
        "validate_grounding",
        "revise_claims",
        "human_review",
        "finalize",
        "fail",
    }
    assert expected_nodes.issubset(uncompiled_graph.nodes.keys())


@pytest.mark.asyncio
async def test_irrelevant_search_results_stop_before_human_or_llm_synthesis():
    """A lexical near-miss must be a clear no-results outcome, never a report."""
    result = await screen_papers_node(
        {
            "original_topic": "Quantum Telepathy",
            "sub_queries": ["Quantum Telepathy"],
            "max_results": 10,
            "papers": [
                paper(
                    "W-teleport",
                    "Quantum teleportation in communication networks",
                    "We evaluate entanglement-assisted quantum teleportation protocols for networks.",
                )
            ],
        }
    )

    assert result["papers"] == []
    assert "Không có bài báo nào phù hợp để tổng hợp" in result["error"]
    assert "NO_RELEVANT_PAPERS" in result["source_warnings"]

    from src.agents.litreview.workflow.graph import after_screen_papers

    assert after_screen_papers(result) == "fail"


@pytest.mark.asyncio
async def test_intent_guardrail_routes_out_of_scope_without_research(monkeypatch):
    class FakeInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs):
            from src.agents.litreview.prompts.intent import IntentClassification

            return IntentClassification(intent="out_of_scope", reason="General coding request")

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FakeInvoker)
    result = await intent_guardrail_node({"original_topic": "Write a Python web scraper"})

    assert result["intent"] == "out_of_scope"
    assert result["decisions"][-1]["action"] == "finish"
    declined = await out_of_scope_node({"original_topic": "Write a Python web scraper"})
    assert "literature-review" in declined["assistant_response"]


@pytest.mark.asyncio
async def test_intent_guardrail_allows_litreview(monkeypatch):
    class FakeInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs):
            from src.agents.litreview.prompts.intent import IntentClassification

            return IntentClassification(intent="litreview", reason="Academic synthesis request")

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FakeInvoker)
    result = await intent_guardrail_node({"original_topic": "Review evidence on AI feedback in education"})

    assert result["intent"] == "litreview"
    assert result["status"] == "running"


@pytest.mark.asyncio
async def test_intent_guardrail_blocks_unsafe_request_before_research(monkeypatch):
    class FakeInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs):
            from src.agents.litreview.prompts.intent import IntentClassification

            return IntentClassification(intent="unsafe", reason="Dangerous actionable request")

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FakeInvoker)
    result = await intent_guardrail_node({"original_topic": "Give me dangerous instructions"})

    assert result["intent"] == "unsafe"
    assert result["decisions"][-1]["action"] == "finish"
    declined = await out_of_scope_node({"original_topic": "Give me dangerous instructions", "intent": "unsafe"})
    assert "dangerous" in declined["assistant_response"]


@pytest.mark.asyncio
async def test_intent_guardrail_fails_closed_when_llm_is_unavailable(monkeypatch):
    class FailingInvoker:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FailingInvoker)
    result = await intent_guardrail_node({"original_topic": "Review recent papers on climate change"})

    assert result["intent"] == "unsafe"
    assert result["status"] == "approved"


@pytest.mark.asyncio
async def test_compiled_plan_search_preserves_topic_and_uses_llm_normalization(monkeypatch):
    from langgraph.graph import END, StateGraph

    from src.agents.litreview.prompts.query_planning import SubQueryPlan

    class FakePlanner:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs, **_kwargs):
            return SubQueryPlan(
                normalized_question="Effects of AI feedback on university student self-regulation",
                sub_queries=["AI feedback effects on university student self-regulated learning in online courses"],
                required_terms=["self-regulated learning"],
                excluded_terms=["primary school"],
            )

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FakePlanner)

    requested_topic = (
        "The Effect of AI-Generated Personalized Feedback on Self-Regulated "
        "Learning Among University Students in Online Courses"
    )
    workflow = StateGraph(AgentState)
    workflow.add_node("plan_search", plan_search_node)
    workflow.set_entry_point("plan_search")
    workflow.add_edge("plan_search", END)

    result = await workflow.compile().ainvoke({"original_topic": requested_topic})

    assert result["original_topic"] == requested_topic
    assert result["search_query"] == "Effects of AI feedback on university student self-regulation"
    assert result["normalized_question"] == result["search_query"]
    assert result["query_history"] == [result["search_query"]]
    assert result["publication_year_range"] is None


@pytest.mark.asyncio
async def test_plan_search_preserves_explicit_publication_year_range(monkeypatch):
    from src.agents.litreview.prompts.query_planning import SubQueryPlan

    class FakePlanner:
        def __init__(self, *_args, **_kwargs):
            pass

        async def ainvoke(self, _inputs, **_kwargs):
            return SubQueryPlan(
                normalized_question="AI triage studies published from 2018",
                sub_queries=["AI triage in emergency departments from 2018 methods and outcomes"],
                publication_year_range=[2018, None],
            )

    monkeypatch.setattr("src.agents.litreview.workflow.nodes._StructuredLLMInvoker", FakePlanner)

    result = await plan_search_node({"original_topic": "Tìm nghiên cứu AI triage từ năm 2018"})

    assert result["publication_year_range"] == (2018, None)


@pytest.mark.asyncio
async def test_plan_search_rejects_missing_topic_instead_of_using_a_default():
    with pytest.raises(ValueError, match="Missing original_topic"):
        await plan_search_node({})


@pytest.mark.asyncio
async def test_academic_source_search_overfetches_before_ranking(monkeypatch):
    calls = []

    async def fake_search(payload):
        calls.append(payload)
        return []

    class FakeSearchTool:
        ainvoke = staticmethod(fake_search)

    monkeypatch.setattr("src.agents.litreview.workflow.nodes.search_academic_sources", FakeSearchTool())

    result = await search_academic_sources_node(
        {
            "original_topic": "personalized feedback and self-regulated learning",
            "search_query": "personalized feedback and self-regulated learning",
            "max_results": 10,
        }
    )

    assert calls == [
        {
            "query": "personalized feedback and self-regulated learning",
            "limit": 20,
        }
    ]
    assert result["papers"] == []


@pytest.mark.asyncio
async def test_academic_source_search_hard_filters_an_explicit_publication_year_range(monkeypatch):
    async def fake_search(_payload):
        return [
            paper("W2003", "Older", "abstract", year=2003),
            paper("W2017", "Before range", "abstract", year=2017),
            paper("W2018", "Range start", "abstract", year=2018),
            paper("W2024", "In range", "abstract", year=2024),
            {**paper("Wunknown", "Unknown year", "abstract"), "year": None},
        ]

    class FakeSearchTool:
        ainvoke = staticmethod(fake_search)

    monkeypatch.setattr("src.agents.litreview.workflow.nodes.search_academic_sources", FakeSearchTool())

    result = await search_academic_sources_node(
        {
            "original_topic": "AI triage from 2018",
            "search_query": "AI triage from 2018",
            "publication_year_range": (2018, None),
        }
    )

    assert [item["paper_id"] for item in result["papers"]] == ["W2018", "W2024"]


@pytest.mark.asyncio
async def test_academic_source_search_hard_filters_papers_before_a_year(monkeypatch):
    async def fake_search(_payload):
        return [
            paper("W2003", "Older", "abstract", year=2003),
            paper("W2017", "Last allowed", "abstract", year=2017),
            paper("W2018", "Outside range", "abstract", year=2018),
            {**paper("Wunknown", "Unknown year", "abstract"), "year": None},
        ]

    class FakeSearchTool:
        ainvoke = staticmethod(fake_search)

    monkeypatch.setattr("src.agents.litreview.workflow.nodes.search_academic_sources", FakeSearchTool())

    result = await search_academic_sources_node(
        {
            "original_topic": "AI triage before 2018",
            "search_query": "AI triage before 2018",
            "publication_year_range": (None, 2017),
        }
    )

    assert [item["paper_id"] for item in result["papers"]] == ["W2003", "W2017"]


@pytest.mark.asyncio
async def test_validated_claim_is_linked_to_evidence_row_without_fabricated_outputs(monkeypatch):
    from src.agents.litreview.prompts.extraction import (
        BatchExtractionResult,
        ExtractedClaim,
        ExtractedQuote,
        PaperExtraction,
    )
    from src.agents.litreview.prompts.synthesis import SynthesisResult
    from src.agents.litreview.prompts.validation import EntailmentResult

    class MockLLM:
        def with_structured_output(self, schema):
            if schema == BatchExtractionResult:

                class MockExtractor:
                    async def ainvoke(self, *args, **kwargs):
                        return BatchExtractionResult(
                            extracted_papers=[
                                PaperExtraction(
                                    paper_id="W001",
                                    claims=[
                                        ExtractedClaim(
                                            claim_type="contribution",
                                            text="We report a grounded result",
                                            evidence_quotes=[ExtractedQuote(quote="We report a grounded result")],
                                            relevance="direct",
                                            relevance_reason="It directly answers the topic.",
                                        )
                                    ],
                                )
                            ]
                        )

                class MockPipe:
                    def __or__(self, other):
                        return MockExtractor()

                monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_extraction_prompt", lambda: MockPipe())
                return MockExtractor()
            elif schema == SynthesisResult:

                class MockSynthesizer:
                    async def ainvoke(self, *args, **kwargs):
                        return SynthesisResult(themes=[], potential_gaps=[])

                class MockPipe:
                    def __or__(self, other):
                        return MockSynthesizer()

                monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_synthesis_prompt", lambda: MockPipe())
                return MockSynthesizer()
            elif schema == EntailmentResult:

                class MockEntailment:
                    async def ainvoke(self, *args, **kwargs):
                        return EntailmentResult(entails=True, reason="Mock passed")

                class MockPipe:
                    def __or__(self, other):
                        return MockEntailment()

                monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_entailment_prompt", lambda: MockPipe())
                return MockEntailment()
            return self

    class MockPrompt:
        def __or__(self, other):
            return other

    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm", lambda: MockLLM())
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm_fallbacks", lambda: [])
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_extraction_prompt", lambda: MockPrompt())
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_synthesis_prompt", lambda: MockPrompt())
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_entailment_prompt", lambda: MockPrompt())
    source = paper(
        "W001",
        "Grounded paper",
        "We report a grounded result based on the supplied evidence. "
        "The remainder of the abstract provides additional context.",
    )
    state = {"papers": [source], "original_topic": "grounded review"}
    state.update(await extract_evidence_node(state))
    state.update(await validate_grounding_node(state))
    state.update(await synthesize_claims_node(state))

    assert [claim["claim_type"] for claim in state["claims"]] == ["contribution"]
    assert state["evidence_rows"][0]["contribution_claim_id"] == state["claims"][0]["claim_id"]
    assert state["evidence_rows"][0]["method_claim_id"] is None
    assert state["themes"] == []
    assert state["potential_gaps"] == []


@pytest.mark.asyncio
async def test_academic_search_uses_only_openalex_and_returns_canonical_work_id():
    abstract_words = " ".join(["grounded"] * 60)
    positions = {"grounded": list(range(60))}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openalex.org"
        assert request.url.params["per_page"] == "10"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "display_name": "Grounded OpenAlex Paper",
                        "authorships": [{"author": {"display_name": "Ada Researcher"}}],
                        "publication_year": 2024,
                        "doi": "https://doi.org/10.1234/grounded",
                        "abstract_inverted_index": positions,
                        "cited_by_count": 12,
                        "open_access": {"is_oa": True},
                        "primary_location": {},
                    }
                ]
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = AcademicSearchService(client)
        papers, warnings = await service.search("grounded review", 10)

    assert len(abstract_words) >= 200
    assert warnings == []
    assert papers[0]["paper_id"] == "W123"
    assert papers[0]["url"] == "https://doi.org/10.1234/grounded"


@pytest.mark.asyncio
async def test_search_academic_sources_preserves_papers_across_attempts(monkeypatch):
    existing_paper = paper("W001", "Existing Paper", "Abstract text")

    async def fake_search(payload):
        return []

    class FakeSearchTool:
        ainvoke = staticmethod(fake_search)

    monkeypatch.setattr("src.agents.litreview.workflow.nodes.search_academic_sources", FakeSearchTool())

    state = {
        "original_topic": "niche topic",
        "search_query": "niche topic survey review overview",
        "search_attempt": 1,
        "papers": [existing_paper],
        "max_results": 10,
    }

    result = await search_academic_sources_node(state)
    assert result["papers"] == [existing_paper]
    assert result["search_attempt"] == 2
