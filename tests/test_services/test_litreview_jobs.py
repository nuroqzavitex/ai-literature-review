from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agents.litreview.application.jobs import LitReviewJobService


class _AsyncContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return None


class _CompletedAgent:
    def __init__(self, state):
        self.state = state

    async def astream(self, *_args, **_kwargs):
        yield {"finalize": {"status": "approved"}}

    async def aget_state(self, _config):
        return SimpleNamespace(values=self.state, next=())


class _Graph:
    def __init__(self, agent):
        self.agent = agent

    def compile(self, *, checkpointer):
        return self.agent


@pytest.mark.asyncio
async def test_resume_persists_complete_report_before_finalizing():
    final_state = {
        "job_id": "job_1",
        "status": "approved",
        "papers": [{"paper_id": "paper_1"}],
        "claims": [{"claim_id": "claim_1", "validation_status": "valid"}],
        "references": [{"paper_id": "paper_1", "title": "Test paper"}],
        "literature_review": {"introduction": "Completed review", "sections": []},
    }
    repository = MagicMock(database_url="postgresql://test")
    service = LitReviewJobService(repository=repository)

    with (
        patch(
            "src.agents.litreview.application.jobs.AsyncPostgresSaver.from_conn_string", return_value=_AsyncContext()
        ),
        patch("src.agents.litreview.application.jobs.uncompiled_graph", _Graph(_CompletedAgent(final_state))),
        patch("src.agents.litreview.application.jobs._persist_report_message"),
    ):
        await service.resume("job_1", {"stage": "papers", "mode": "ranked"})

    persisted = repository.complete_job.call_args.args[1]
    assert persisted["claims"] == final_state["claims"]
    assert persisted["references"] == final_state["references"]
    assert persisted["literature_review"] == final_state["literature_review"]
    assert repository.complete_job.call_args.kwargs == {"mark_waiting": False}
    calls = [entry[0] for entry in repository.method_calls]
    assert calls.index("complete_job") < calls.index("finalize_job")
