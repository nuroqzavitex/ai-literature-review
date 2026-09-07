from types import SimpleNamespace

import pytest

from src.api.routers import research_copilot as routes
from src.api.routers.research_copilot import _answer_report_followup, _has_grounded_followup_context


def test_first_turn_does_not_expose_report_context_to_rag_router() -> None:
    conversation = {"active_report_version_id": "rv_1"}

    assert not _has_grounded_followup_context(conversation, [])


def test_later_turn_can_use_the_conversation_report_context() -> None:
    conversation = {"active_report_version_id": "rv_1"}
    messages = [{"role": "user", "text": "Initial research question"}]

    assert _has_grounded_followup_context(conversation, messages)


def test_history_without_a_report_cannot_enable_rag() -> None:
    conversation = {"active_report_version_id": None}
    messages = [{"role": "user", "text": "Initial research question"}]

    assert not _has_grounded_followup_context(conversation, messages)


@pytest.mark.asyncio
async def test_report_followup_routes_grounded_intent_to_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class PlanningService:
        async def classify_workspace_intent(self, text: str, *, has_report_context: bool):
            assert text == "Explain KTAS"
            assert has_report_context
            return SimpleNamespace(intent="grounded_rag"), "llm"

    class ChatService:
        async def answer_message(self, conversation, actor, text, *, mode, history):
            calls.append("rag")
            return {"message_type": "grounded_answer", "text": "KTAS ..."}

        def answer_out_of_scope_followup(self, conversation, text):
            calls.append("out_of_scope")
            return {"message_type": "out_of_scope", "text": "Not related"}

    monkeypatch.setattr(routes, "research_planning_service", PlanningService())
    monkeypatch.setattr(routes, "v2_service", ChatService())

    result = await _answer_report_followup(
        {"conversation_id": "conv_1", "active_report_version_id": "rv_1"},
        {"actor_id": "actor_1"},
        "Explain KTAS",
        [{"role": "user", "text": "Initial report request"}],
    )

    assert result["message_type"] == "grounded_answer"
    assert calls == ["rag"]


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["clarify", "literature_review", "research_gap", "unsafe"])
async def test_report_followup_never_calls_rag_for_other_intents(monkeypatch: pytest.MonkeyPatch, intent: str) -> None:
    calls: list[str] = []

    class PlanningService:
        async def classify_workspace_intent(self, text: str, *, has_report_context: bool):
            return SimpleNamespace(intent=intent), "llm"

    class ChatService:
        async def answer_message(self, conversation, actor, text, *, mode, history):
            calls.append("rag")
            return {"message_type": "grounded_answer", "text": "Unexpected"}

        def answer_out_of_scope_followup(self, conversation, text):
            calls.append("out_of_scope")
            return {"message_type": "out_of_scope", "text": "Not related"}

    monkeypatch.setattr(routes, "research_planning_service", PlanningService())
    monkeypatch.setattr(routes, "v2_service", ChatService())

    result = await _answer_report_followup(
        {"conversation_id": "conv_1", "active_report_version_id": "rv_1"},
        {"actor_id": "actor_1"},
        "hello",
        [{"role": "user", "text": "Initial report request"}],
    )

    assert result["message_type"] == "out_of_scope"
    assert calls == ["out_of_scope"]
