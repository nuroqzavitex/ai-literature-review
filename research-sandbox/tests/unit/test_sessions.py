from datetime import datetime, timezone

import pytest

from sandbox_service.domain.errors import SandboxSessionNotFound, SourceNotReviewed
from sandbox_service.domain.sessions import (
    CreateSandboxSessionRequest,
    ResearchContextSnapshot,
    SandboxEntrypoint,
    SandboxMode,
    SandboxSessionStatus,
)
from sandbox_service.repositories.memory import InMemorySandboxSessionRepository
from sandbox_service.session_service import SandboxSessionService
from tests.fakes import FakeProjectAIClient, FakeResearchContextProvider, FakeSandboxExecutor


@pytest.mark.asyncio
async def test_creates_draft_session_on_demand_without_ai_or_worker() -> None:
    repository = InMemorySandboxSessionRepository()
    service = SandboxSessionService(repository=repository)
    ai = FakeProjectAIClient()
    executor = FakeSandboxExecutor()

    session = await service.create_session(
        project_id="project-a",
        actor_id="user-a",
        request=CreateSandboxSessionRequest(
            mode=SandboxMode.HYPOTHESIS,
            entrypoint=SandboxEntrypoint.MANUAL,
            title="Manual question",
            initial_question="Does intervention X change outcome Y?",
        ),
    )

    assert session.status is SandboxSessionStatus.DRAFT
    assert session.context_snapshot_id is None
    assert session.creator_id == "user-a"
    assert ai.calls == []
    assert executor.submissions == []
    assert repository.status_history[0]["to_status"] == "draft"


@pytest.mark.asyncio
async def test_get_session_by_id_and_pins_trusted_context() -> None:
    snapshot = ResearchContextSnapshot(
        project_id="project-a",
        source_type=SandboxEntrypoint.GRAPHRAG_ANSWER,
        source_status="reviewed",
        content_hash="sha256:context-a",
        created_at=datetime.now(timezone.utc),
    )
    provider = FakeResearchContextProvider({("project-a", "answer-7"): snapshot})
    repository = InMemorySandboxSessionRepository()
    service = SandboxSessionService(repository=repository, context_provider=provider)

    created = await service.create_session(
        project_id="project-a",
        actor_id="user-a",
        request=CreateSandboxSessionRequest(
            mode="hypothesis",
            entrypoint="graphrag_answer",
            source_resource_id="answer-7",
            title="Pinned GraphRAG context",
        ),
    )
    loaded = await service.get_session(project_id="project-a", session_id=created.session_id)

    assert loaded == created
    assert loaded.status is SandboxSessionStatus.DRAFT
    assert loaded.context_snapshot_id == snapshot.context_id
    assert loaded.context_hash == "sha256:context-a"
    assert repository.context_snapshots[snapshot.context_id] == snapshot
    assert provider.calls == [{"project_id": "project-a", "source_resource_id": "answer-7"}]


@pytest.mark.asyncio
async def test_project_scope_rejects_cross_project_session_and_source_spoof() -> None:
    repository = InMemorySandboxSessionRepository()
    provider = FakeResearchContextProvider()
    service = SandboxSessionService(repository=repository, context_provider=provider)
    created = await service.create_session(
        project_id="project-a",
        actor_id="user-a",
        request=CreateSandboxSessionRequest(
            mode="graph_overlay", entrypoint="manual", title="Private overlay"
        ),
    )

    with pytest.raises(SandboxSessionNotFound):
        await service.get_session(project_id="project-b", session_id=created.session_id)
    with pytest.raises(SourceNotReviewed):
        await service.create_session(
            project_id="project-b",
            actor_id="user-b",
            request=CreateSandboxSessionRequest(
                mode="hypothesis",
                entrypoint="graphrag_answer",
                source_resource_id="answer-owned-by-a",
                title="Spoofed source",
            ),
        )
