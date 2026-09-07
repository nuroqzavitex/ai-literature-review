import pytest

from src.services import research_planning


def test_fallback_classifies_recent_work_summary_as_research() -> None:
    plan = research_planning._fallback_plan("Summarize recent works on RAG factual accuracy")

    assert plan.intent == "research"
    assert len(plan.sub_queries) >= 3
    assert set(plan.sources) == {"openalex", "semantic_scholar", "arxiv"}


def test_workspace_router_prompt_prioritizes_acronyms_in_report_context() -> None:
    messages = research_planning._WORKSPACE_INTENT_PROMPT.format_messages(prompt="KTAS là gì?", has_report_context=True)
    prompt = "\n".join(str(message.content) for message in messages)

    assert "standalone acronym" in prompt
    assert "KTAS là gì?" in prompt
    assert "grounded_rag" in prompt


@pytest.mark.asyncio
async def test_llm_plan_is_normalized_and_deduplicated(monkeypatch) -> None:
    class FakeChain:
        async def ainvoke(self, _input):
            return research_planning.ResearchIntentPlan(
                intent="research",
                normalized_question="RAG and factual accuracy",
                sub_queries=[
                    "RAG methods for improving factual accuracy in language models",
                    "RAG methods for improving factual accuracy in language models",
                    "RAG techniques to reduce hallucination in language model outputs",
                ],
                sources=["openalex", "arxiv"],
                selection_criteria=["relevance"],
            )

    class FakePrompt:
        def __or__(self, _runnable):
            return FakeChain()

    class FakeLLM:
        def with_structured_output(self, _schema):
            return object()

    monkeypatch.setattr(research_planning, "_PLANNING_PROMPT", FakePrompt())
    monkeypatch.setattr(research_planning, "get_llm", lambda: FakeLLM())

    plan, routing = await research_planning.ResearchPlanningService().plan("Tell me about RAG")

    assert routing == "llm"
    assert plan.sub_queries == [
        "RAG methods for improving factual accuracy in language models",
        "RAG techniques to reduce hallucination in language model outputs",
    ]
    assert plan.sources == ["openalex", "arxiv"]


@pytest.mark.asyncio
async def test_document_search_seed_uses_bounded_untrusted_document_context(monkeypatch) -> None:
    captured = {}

    class FakeChain:
        async def ainvoke(self, value):
            captured.update(value)
            return research_planning.DocumentSearchSeed(
                topic="How does AI-assisted triage affect emergency department outcomes?"
            )

    class FakePrompt:
        def __or__(self, _runnable):
            return FakeChain()

    class FakeLLM:
        def with_structured_output(self, _schema):
            return object()

    monkeypatch.setattr(research_planning, "_DOCUMENT_SEARCH_SEED_PROMPT", FakePrompt())
    monkeypatch.setattr(research_planning, "get_llm", lambda: FakeLLM())

    seed, routing = await research_planning.ResearchPlanningService().document_search_seed(
        "x" * 30_000, "Focus on equity"
    )

    assert routing == "llm"
    assert seed.topic.startswith("How does AI-assisted triage")
    assert len(captured["document_text"]) == 24_000
    assert captured["focus"] == "Focus on equity"


@pytest.mark.asyncio
async def test_workspace_intent_routes_doi_requests_to_literature_review(monkeypatch) -> None:
    class FakeChain:
        async def ainvoke(self, _input):
            return research_planning.WorkspaceIntent(
                intent="literature_review",
                reason="A DOI is handled by the literature-review workflow.",
            )

    class FakePrompt:
        def __or__(self, _runnable):
            return FakeChain()

    class FakeLLM:
        def with_structured_output(self, _schema):
            return object()

    monkeypatch.setattr(research_planning, "_WORKSPACE_INTENT_PROMPT", FakePrompt())
    monkeypatch.setattr(research_planning, "get_llm", lambda: FakeLLM())

    intent, routing = await research_planning.ResearchPlanningService().classify_workspace_intent(
        "Tóm tắt bài có DOI 10.1145/3442188.3445922"
    )

    assert routing == "llm"
    assert intent.intent == "literature_review"


@pytest.mark.asyncio
async def test_workspace_intent_routes_a_gap_request_to_the_standalone_workflow(monkeypatch) -> None:
    class FakeChain:
        async def ainvoke(self, _input):
            return research_planning.WorkspaceIntent(
                intent="research_gap",
                reason="The user asked to identify under-studied evaluation settings.",
            )

    class FakePrompt:
        def __or__(self, _runnable):
            return FakeChain()

    class FakeLLM:
        def with_structured_output(self, _schema):
            return object()

    monkeypatch.setattr(research_planning, "_WORKSPACE_INTENT_PROMPT", FakePrompt())
    monkeypatch.setattr(research_planning, "get_llm", lambda: FakeLLM())

    intent, routing = await research_planning.ResearchPlanningService().classify_workspace_intent(
        "Tìm research gap về đánh giá độ tin cậy của RAG"
    )

    assert routing == "llm"
    assert intent.intent == "research_gap"


@pytest.mark.asyncio
async def test_workspace_intent_allows_grounded_rag_only_with_report_context(monkeypatch) -> None:
    class FakeChain:
        async def ainvoke(self, _input):
            return research_planning.WorkspaceIntent(
                intent="grounded_rag",
                reason="The user is asking about the current report.",
            )

    class FakePrompt:
        def __or__(self, _runnable):
            return FakeChain()

    class FakeLLM:
        def with_structured_output(self, _schema):
            return object()

    monkeypatch.setattr(research_planning, "_WORKSPACE_INTENT_PROMPT", FakePrompt())
    monkeypatch.setattr(research_planning, "get_llm", lambda: FakeLLM())
    service = research_planning.ResearchPlanningService()

    grounded, _ = await service.classify_workspace_intent(
        "What are this report's limitations?", has_report_context=True
    )
    no_corpus, _ = await service.classify_workspace_intent(
        "What are this report's limitations?", has_report_context=False
    )

    assert grounded.intent == "grounded_rag"
    assert no_corpus.intent == "clarify"


@pytest.mark.asyncio
async def test_workspace_intent_accepts_json_wrapped_in_markdown_fence(monkeypatch) -> None:
    class FakePrompt:
        def format_messages(self, **_inputs):
            return []

    class FakeClient:
        async def ainvoke(self, _messages):
            return '```json\n{"intent":"literature_review","reason":"The user requested a topic review."}\n```'

    class FakeCandidate:
        native_schema_supported = False
        client = FakeClient()

    monkeypatch.setattr(research_planning, "_WORKSPACE_INTENT_PROMPT", FakePrompt())
    monkeypatch.setattr(research_planning, "get_llm", lambda: FakeCandidate())

    intent, routing = await research_planning.ResearchPlanningService().classify_workspace_intent(
        "Tôi muốn tìm bài báo về con gà có trước hay quả trứng có trước"
    )

    assert routing == "llm"
    assert intent.intent == "literature_review"


@pytest.mark.asyncio
async def test_non_native_schema_provider_is_prompted_for_json(monkeypatch) -> None:
    class FakePrompt:
        def format_messages(self, **_inputs):
            return []

    class FakeClient:
        async def ainvoke(self, _messages):
            return '{"intent":"research","normalized_question":"RAG factual accuracy","sub_queries":["RAG methods for factual accuracy evaluation in language models"],"sources":["openalex"],"selection_criteria":[]}'

    class FakeCandidate:
        native_schema_supported = False
        client = FakeClient()

    monkeypatch.setattr(research_planning, "_PLANNING_PROMPT", FakePrompt())
    monkeypatch.setattr(research_planning, "get_llm", lambda: FakeCandidate())

    plan, routing = await research_planning.ResearchPlanningService().plan("RAG factual accuracy")

    assert routing == "llm"
    assert plan.intent == "research"
    assert plan.sub_queries == ["RAG methods for factual accuracy evaluation in language models"]
