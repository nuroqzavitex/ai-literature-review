import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.agents.litreview.application.copilot import V2Service
from src.agents.litreview.infrastructure.repositories.copilot import ProjectResearchBusyError, V2Repository
from src.agents.litreview.infrastructure.repositories.jobs import JobRepository
from src.api.routers import literature_reviews as routes
from src.api.routers import research_copilot as v2_routes
from src.services import research_copilot as v2_service_module


@pytest.fixture
def v2_isolated(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'v2.db'}"
    jobs = JobRepository(url)
    repository = V2Repository(url)
    job_service = SimpleNamespace(run=AsyncMock(), resume=AsyncMock(), repository=jobs)
    service = V2Service(repository, jobs, job_service)
    monkeypatch.setattr(v2_routes, "v2_repository", repository)
    monkeypatch.setattr(v2_routes, "v2_service", service)
    monkeypatch.setattr(v2_routes, "v1_repository", jobs)
    monkeypatch.setattr(v2_routes, "job_service", job_service)
    monkeypatch.setattr(routes, "repository", jobs)
    monkeypatch.setattr(routes, "job_service", job_service)
    return repository, jobs, service


async def login(client, token="researcher:alice"):
    response = await client.post("/api/v1/auth/session", json={"bootstrap_token": token})
    assert response.status_code == 201
    return response.json()["actor"]


async def create_project(client):
    response = await client.post("/api/v1/projects", json={"name": "Grounded project", "description": "test"})
    assert response.status_code == 201
    return response.json()["project"]


@pytest.mark.asyncio
async def test_uploaded_document_creates_a_temporary_search_seed(client, v2_isolated, tmp_path, monkeypatch):
    await login(client)
    project = await create_project(client)
    temporary_root = tmp_path / "uploads"

    def extract(path):
        assert path.suffix == ".pdf"
        assert path.read_bytes() == b"example PDF bytes"
        return "Emergency department triage with machine learning outcomes."

    async def seed(document_text, focus):
        assert "triage" in document_text
        assert focus == "Focus on fairness"
        return SimpleNamespace(topic="How does machine learning affect fairness in emergency triage?"), "llm"

    monkeypatch.setattr(v2_routes, "extract_uploaded_document_text", extract)
    monkeypatch.setattr(v2_routes, "get_settings", lambda: SimpleNamespace(paper_storage_dir=str(temporary_root)))
    monkeypatch.setattr(v2_routes.research_planning_service, "document_search_seed", seed)

    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/document-search-seed",
        data={"focus": "Focus on fairness"},
        files={"document": ("triage.pdf", b"example PDF bytes", "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["filename"] == "triage.pdf"
    assert response.json()["routing"] == "llm"
    assert not list((temporary_root / "temporary-uploads").glob("*"))


@pytest.mark.asyncio
async def test_uploaded_document_rejects_unsupported_file_type(client, v2_isolated):
    await login(client)
    project = await create_project(client)

    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/document-search-seed",
        files={"document": ("notes.txt", b"not a PDF", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "UNSUPPORTED_DOCUMENT"


def report_fixture():
    return {
        "original_topic": "AI literature review",
        "search_query": "AI literature review",
        "papers": [
            {
                "paper_id": "W1",
                "title": "Grounded review",
                "authors": ["A"],
                "year": 2025,
                "doi": None,
                "url": "https://openalex.org/W1",
                "abstract": "The method reduces review time.",
            }
        ],
        "claims": [
            {
                "claim_id": "c1",
                "claim_type": "contribution",
                "text": "The method reduces review time.",
                "supporting_paper_ids": ["W1"],
                "evidence": [{"paper_id": "W1", "quote": "The method reduces review time.", "section": "abstract"}],
                "validation_status": "valid",
                "validation_errors": [],
            }
        ],
        "evidence_rows": [],
        "themes": [],
        "decision_trace": [],
        "potential_gaps": [
            {
                "gap_id": "gap1",
                "aspect": "rural settings",
                "papers_checked": 1,
                "coverage": [{"paper_id": "W1", "mentioned": False, "evidence_quote": None}],
                "scope_statement": "Within 1 OpenAlex abstract, rural settings were not reported.",
            }
        ],
        "references": [
            {
                "paper_id": "W1",
                "title": "Grounded review",
                "authors": ["A"],
                "year": 2025,
                "doi": None,
                "url": "https://openalex.org/W1",
                "source": "openalex",
                "metadata_valid": True,
            }
        ],
        "scope_disclaimer": "Limited to this OpenAlex abstract corpus.",
    }


@pytest.mark.asyncio
async def test_v2_requires_opaque_session(client, v2_isolated):
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    await login(client)
    response = await client.get("/api/v1/me")
    assert response.status_code == 200
    assert response.json()["actor"]["actor_id"] == "alice"


@pytest.mark.asyncio
async def test_v2_forbids_identity_extra_fields(client, v2_isolated):
    await login(client)
    response = await client.post(
        "/api/v1/projects",
        json={"name": "Project", "description": "", "user_id": "mallory", "role": "owner"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_review_trace_requires_session_and_project_access(client, v2_isolated):
    await login(client)
    project = await create_project(client)
    created = await client.post(
        f"/api/v1/projects/{project['project_id']}/reviews",
        json={"topic": "Private trace", "max_results": 10},
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    await client.delete("/api/v1/auth/session")
    anonymous = await client.get(f"/api/v1/reviews/{job_id}/trace")
    assert anonymous.status_code == 401

    await login(client, token="researcher:bob")
    forbidden = await client.get(f"/api/v1/reviews/{job_id}/trace")
    assert forbidden.status_code == 404


@pytest.mark.asyncio
async def test_selected_source_chat_accepts_only_approved_project_reports(client, v2_isolated, monkeypatch):
    repository, jobs, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    job_id = "job_selected_source_chat"
    jobs.create_job(job_id, "alice", "researcher", "AI literature review", 10)
    repository.link_review_job(project["project_id"], job_id, "alice", "project_review")
    jobs.complete_job(job_id, report_fixture())

    blocked = await client.post(
        f"/api/v1/projects/{project['project_id']}/source-chat",
        json={"job_ids": [job_id], "text": "What improves review time?"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "SOURCE_NOT_APPROVED"

    jobs.update_status(job_id, "approved")
    monkeypatch.setattr(v2_routes, "get_settings", lambda: SimpleNamespace(qdrant_enabled=False))
    from src.services import llm

    monkeypatch.setattr(
        llm,
        "get_llm",
        lambda: SimpleNamespace(
            ainvoke=AsyncMock(return_value=SimpleNamespace(content="Grounding improves review time. [S1]"))
        ),
    )
    answer = await client.post(
        f"/api/v1/projects/{project['project_id']}/source-chat",
        json={"job_ids": [job_id], "text": "What improves review time?"},
    )

    assert answer.status_code == 200
    payload = answer.json()
    assert payload["selected_job_ids"] == [job_id]
    assert payload["fallback_job_ids"] == [job_id]
    assert payload["citations"][0]["source_url"] == "https://openalex.org/W1"


@pytest.mark.asyncio
async def test_visual_artifact_uses_the_saved_latex_source(client, v2_isolated, monkeypatch):
    repository, jobs, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    job_id = "job_visual_artifact"
    jobs.create_job(job_id, "alice", "researcher", "AI literature review", 10)
    repository.link_review_job(project["project_id"], job_id, "alice", "project_review")
    jobs.complete_job(job_id, report_fixture())
    jobs.update_status(job_id, "approved")
    captured: dict[str, str] = {}

    async def generate(**kwargs):
        captured.update(kwargs)
        return v2_routes.GeneratedVisualArtifact.model_validate(
            {
                "title": "Bản đồ AI",
                "overview": "Tổng hợp theo bản LaTeX đã lưu.",
                "branches": [{"title": f"Nhánh {index}", "points": ["Ý 1", "Ý 2"]} for index in range(1, 5)],
                "slides": [],
            }
        )

    monkeypatch.setattr(v2_routes, "_generate_visual_artifact", generate)
    latex = "\\section{Bản đã chỉnh sửa}\\nNội dung chỉ có trong LaTeX này."
    response = await client.post(
        f"/api/v1/reviews/{job_id}/visual-artifact",
        json={"artifact_type": "mindmap", "latex": latex},
    )

    assert response.status_code == 200
    assert captured["latex"] == latex
    assert "[P1] Grounded review (2025)" in captured["related_papers"]
    assert response.json()["source"] == "saved_review_corpus"
    assert len(response.json()["artifact"]["branches"]) == 4


@pytest.mark.asyncio
async def test_visual_artifact_keeps_complete_draft_when_editorial_pass_fails(monkeypatch):
    from src.services import llm

    draft = {
        "title": "AI triage",
        "overview": "Evidence summary.",
        "branches": [{"title": f"Branch {index}", "points": ["Point one", "Point two"]} for index in range(1, 7)],
        "slides": [],
    }

    class Candidate:
        native_schema_supported = False
        endpoint = SimpleNamespace(label="test:model")

        def __init__(self):
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            if self.calls == 2:
                raise TimeoutError("editorial pass timed out")
            return SimpleNamespace(content=json.dumps(draft))

    candidate = Candidate()
    monkeypatch.setattr(llm, "get_llm", lambda: candidate)
    monkeypatch.setattr(llm, "get_llm_fallbacks", lambda: [])

    artifact = await v2_routes._generate_visual_artifact(
        artifact_type="mindmap", latex="\\section{Results} Evidence.", topic="AI triage"
    )

    assert artifact.title == draft["title"]
    assert candidate.calls == 2


def test_sparse_mindmap_with_one_supported_branch_is_complete():
    artifact = v2_routes.GeneratedVisualArtifact.model_validate(
        {
            "title": "Evidence map",
            "overview": "Only one evidence-backed theme is available.",
            "branches": [{"title": "Supported finding", "points": ["One grounded point"]}],
            "slides": [],
        }
    )

    assert v2_routes._visual_artifact_is_complete(artifact, "mindmap")


def test_slide_artifact_requires_substantial_speaker_notes():
    payload = {
        "title": "Presentation",
        "overview": "Evidence summary.",
        "branches": [],
        "slides": [
            {
                "title": f"Slide {index}",
                "points": ["Finding one", "Finding two"],
                "speaker_notes": "word " * 120,
            }
            for index in range(1, 7)
        ],
    }
    artifact = v2_routes.GeneratedVisualArtifact.model_validate(payload)

    assert v2_routes._visual_artifact_is_complete(artifact, "slides")
    brief_draft = artifact.model_copy(
        update={
            "slides": [artifact.slides[0].model_copy(update={"speaker_notes": "Brief."}), *artifact.slides[1:]],
        }
    )
    assert v2_routes._visual_artifact_has_valid_structure(brief_draft, "slides")
    assert not v2_routes._visual_artifact_is_complete(brief_draft, "slides")


def test_four_slide_deck_is_a_structurally_valid_draft():
    artifact = v2_routes.GeneratedVisualArtifact.model_validate(
        {
            "title": "Compact presentation",
            "overview": "Evidence summary.",
            "branches": [],
            "slides": [{"title": f"Slide {index}", "points": ["Finding one", "Finding two"]} for index in range(1, 5)],
        }
    )

    assert v2_routes._visual_artifact_has_valid_structure(artifact, "slides")


@pytest.mark.asyncio
async def test_slide_illustrations_are_optional_and_limited(monkeypatch):
    artifact = v2_routes.GeneratedVisualArtifact.model_validate(
        {
            "title": "AI triage",
            "overview": "Evidence summary.",
            "branches": [],
            "slides": [
                {
                    "title": f"Slide {index}",
                    "points": ["Finding one", "Finding two"],
                    "speaker_notes": "A sufficiently long presentation script.",
                    "visual_prompt": "A calm clinical research setting",
                    "visual_alt": "Clinical research illustration",
                }
                for index in range(1, 5)
            ],
        }
    )
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"b64_json": "generated-image"}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, headers, json):
            requests.append({"headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(
        v2_routes,
        "get_settings",
        lambda: SimpleNamespace(
            openai_api_key="test-key",
            slide_image_generation_enabled=True,
            slide_image_max_per_deck=5,
            slide_image_model="gpt-image-2",
            slide_image_quality="low",
        ),
    )
    monkeypatch.setattr(v2_routes.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    illustrated = await v2_routes._add_slide_illustrations(artifact, "AI triage")

    assert len(requests) == 5
    assert all(item["headers"]["Authorization"] == "Bearer test-key" for item in requests)
    assert all(item["json"]["size"] == "1536x1024" for item in requests)
    assert all(item["json"]["output_format"] == "jpeg" for item in requests)
    assert all(item["json"]["output_compression"] == 70 for item in requests)
    assert [bool(slide.image_data_url) for slide in illustrated.slides] == [True, True, True, True, True, False]
    assert illustrated.slides[0].image_data_url == "data:image/jpeg;base64,generated-image"


@pytest.mark.asyncio
async def test_project_owner_can_delete_finished_review_and_dependencies(client, v2_isolated):
    repository, jobs, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    created = await client.post(
        f"/api/v1/projects/{project['project_id']}/reviews",
        json={"topic": "Disposable test review", "max_results": 10},
    )
    assert created.status_code == 202
    job_id = created.json()["job_id"]

    active_delete = await client.delete(f"/api/v1/projects/{project['project_id']}/reviews/{job_id}")
    assert active_delete.status_code == 409
    assert active_delete.json()["detail"]["code"] == "REVIEW_ACTIVE"

    jobs.fail_job(job_id, "test complete")
    version = repository.create_report_version(
        project["project_id"], report_fixture(), "alice", "test fixture", job_id=job_id
    )
    revised_report = report_fixture()
    revised_report["claims"][0]["text"] = "The revised method reduces review time."
    revised_version = repository.create_report_version(
        project["project_id"], revised_report, "alice", "reviewer revision", job_id=job_id
    )
    assert version["version_number"] == 1
    assert revised_version["version_number"] == 2
    next_job_version = repository.create_report_version(
        project["project_id"], report_fixture(), "alice", "second review", job_id="job_second_project_review"
    )
    # A new job in the same project must not reuse version 1 and violate the
    # project-wide unique constraint.
    assert next_job_version["version_number"] == 3
    deleted = await client.delete(f"/api/v1/projects/{project['project_id']}/reviews/{job_id}")
    assert deleted.status_code == 204
    assert repository.project_for_job(job_id) is None
    assert repository.get_report_version(project["project_id"], version["report_version_id"]) is None
    assert repository.get_report_version(project["project_id"], revised_version["report_version_id"]) is None
    assert jobs.get_status(job_id) is None
    listed = await client.get(f"/api/v1/projects/{project['project_id']}/reviews")
    assert listed.json()["items"] == []


@pytest.mark.asyncio
async def test_project_allows_many_threads_but_only_one_running_agent(client, v2_isolated):
    repository, jobs, _ = v2_isolated
    await login(client)
    project = await create_project(client)

    first = await client.post(
        f"/api/v1/projects/{project['project_id']}/reviews",
        json={"topic": "Primary research question", "max_results": 10},
    )
    blocked_second = await client.post(
        f"/api/v1/projects/{project['project_id']}/reviews",
        json={"topic": "Accidental parallel run", "max_results": 10},
    )

    assert first.status_code == 202
    assert blocked_second.status_code == 409
    assert blocked_second.json()["detail"]["code"] == "PROJECT_RESEARCH_BUSY"
    jobs.fail_job(first.json()["job_id"], "first thread stopped")

    second = await client.post(
        f"/api/v1/projects/{project['project_id']}/reviews",
        json={"topic": "Independent follow-up question", "max_results": 10},
    )
    assert second.status_code == 202
    links = repository.list_review_links(project["project_id"])
    assert [link["job_id"] for link in links] == [second.json()["job_id"], first.json()["job_id"]]
    assert jobs.get_status(first.json()["job_id"])["status"] == "error"
    assert jobs.get_status(second.json()["job_id"])["status"] == "queued"
    with pytest.raises(ProjectResearchBusyError):
        repository.update_review_status(first.json()["job_id"], "resuming")


def test_worker_restart_marks_only_interrupted_jobs_as_error(tmp_path):
    jobs = JobRepository(f"sqlite:///{tmp_path / 'jobs.db'}")
    jobs.create_job("running-job", "alice", "researcher", "RAG", 10)
    jobs.update_progress("running-job", "extract_evidence")
    jobs.create_job("waiting-job", "alice", "researcher", "RAG review", 10)
    jobs.update_status("waiting-job", "hitl_waiting")

    interrupted = jobs.fail_orphaned_active_jobs("9999-12-31T23:59:59+00:00")

    assert interrupted == ["running-job"]
    assert jobs.get_status("running-job")["status"] == "error"
    assert jobs.get_status("waiting-job")["status"] == "hitl_waiting"


@pytest.mark.asyncio
async def test_project_owner_can_delete_project_and_all_reviews(client, v2_isolated):
    repository, jobs, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    created = await client.post(
        f"/api/v1/projects/{project['project_id']}/reviews",
        json={"topic": "Disposable project review", "max_results": 10},
    )
    job_id = created.json()["job_id"]

    active_delete = await client.delete(f"/api/v1/projects/{project['project_id']}")
    assert active_delete.status_code == 409
    assert active_delete.json()["detail"]["code"] == "PROJECT_HAS_ACTIVE_REVIEWS"

    jobs.fail_job(job_id, "test complete")
    repository.create_report_version(project["project_id"], report_fixture(), "alice", "test fixture", job_id=job_id)
    deleted = await client.delete(f"/api/v1/projects/{project['project_id']}")
    assert deleted.status_code == 204
    assert repository.get_project(project["project_id"]) is None
    assert repository.project_for_job(job_id) is None
    assert repository.list_report_versions(project["project_id"]) == []
    assert jobs.get_status(job_id) is None
    assert (await client.get("/api/v1/projects")).json()["items"] == []


@pytest.mark.asyncio
async def test_grounded_chat_has_project_version_citation(client, v2_isolated, monkeypatch):
    repository, _, service = v2_isolated
    await login(client)
    project = await create_project(client)
    version = repository.create_report_version(project["project_id"], report_fixture(), "alice", "fixture")
    repository.upsert_gaps_from_report(project["project_id"], version["report_version_id"], report_fixture())
    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/conversations",
        json={"initial_report_version_id": version["report_version_id"]},
    )
    conversation = response.json()["conversation"]
    monkeypatch.setattr(
        service,
        "capability_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("chat rebuilt capability snapshot")),
    )
    response = await client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        json={
            "client_message_id": "turn-1",
            "text": "What does the method report about review time?",
            "expected_report_version_id": version["report_version_id"],
        },
    )
    assert response.status_code == 202, response.text
    message = response.json()["assistant_message"]
    assert message["message_type"] == "grounded_answer"
    assert message["citations"][0]["paper_id"] == "W1"
    assert message["citations"][0]["report_version_id"] == version["report_version_id"]


@pytest.mark.asyncio
async def test_conversation_rag_resolves_a_follow_up_and_uses_indexed_passages(client, v2_isolated, monkeypatch):
    repository, _, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    version = repository.create_report_version(
        project["project_id"], report_fixture(), "alice", "fixture", job_id="job_rag"
    )
    conversation = (
        await client.post(
            f"/api/v1/projects/{project['project_id']}/conversations",
            json={"initial_report_version_id": version["report_version_id"]},
        )
    ).json()["conversation"]
    repository.save_user_message(
        conversation["conversation_id"], "turn-rag", "RAG là gì?", version["report_version_id"]
    )
    seen: dict[str, str] = {}

    class FakeStore:
        async def retrieve_claim_evidence(self, query, job_id, limit):
            seen["query"] = query
            seen["job_id"] = job_id
            seen["limit"] = str(limit)
            return [
                {
                    "paper_id": "W1",
                    "title": "Grounded review",
                    "source_url": "https://openalex.org/W1",
                    "quote": "RAG retrieves relevant passages before generation.",
                    "section": "Methods",
                    "document_id": "W1:chunk:2",
                }
            ]

    class FakeLLM:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content="RAG retrieves relevant passages before generating an answer.")

    monkeypatch.setattr(v2_service_module, "get_settings", lambda: SimpleNamespace(qdrant_enabled=True))
    monkeypatch.setattr(v2_service_module, "QdrantVectorStore", lambda **_kwargs: FakeStore())
    monkeypatch.setattr("src.services.llm.get_llm", lambda: FakeLLM())
    response = await client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        json={
            "client_message_id": "turn-follow-up",
            "text": "Nó có tác dụng gì?",
            "expected_report_version_id": version["report_version_id"],
        },
    )

    assert response.status_code == 202, response.text
    message = response.json()["assistant_message"]
    assert seen == {"query": "RAG: Nó có tác dụng gì?", "job_id": "job_rag", "limit": "6"}
    assert message["content_scope"] == "conversation_report_rag"
    assert message["text"] == "RAG retrieves relevant passages before generating an answer."
    assert message["citations"][0]["quote"] == "RAG retrieves relevant passages before generation."
    assert message["limitations"] == []


@pytest.mark.asyncio
async def test_completed_report_pins_its_originating_conversation_for_vector_rag(client, v2_isolated, monkeypatch):
    repository, jobs, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    conversation = (await client.post(f"/api/v1/projects/{project['project_id']}/conversations", json={})).json()[
        "conversation"
    ]
    repository.link_review_job(
        project["project_id"],
        "job_rag_origin",
        "alice",
        "project_review",
        conversation_id=conversation["conversation_id"],
    )
    jobs.create_job("job_rag_origin", "alice", "researcher", "Vector RAG", 10)
    jobs.complete_job("job_rag_origin", {**report_fixture(), "papers_count": 1})
    refreshed = await client.get(f"/api/v1/conversations/{conversation['conversation_id']}")
    assert refreshed.status_code == 200
    version_id = refreshed.json()["conversation"]["active_report_version_id"]
    assert version_id is not None

    seen: dict[str, str] = {}

    class FakeStore:
        async def retrieve_claim_evidence(self, query, job_id, limit):
            seen.update(query=query, job_id=job_id, limit=str(limit))
            return [
                {
                    "paper_id": "W1",
                    "title": "Grounded review",
                    "source_url": "https://openalex.org/W1",
                    "quote": "The method reduces review time.",
                    "section": "abstract",
                    "document_id": "W1:chunk:0",
                }
            ]

    class FakeLLM:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content="The method reduces review time by streamlining its workflow.")

    monkeypatch.setattr(v2_service_module, "get_settings", lambda: SimpleNamespace(qdrant_enabled=True))
    monkeypatch.setattr(v2_service_module, "QdrantVectorStore", lambda **_kwargs: FakeStore())
    monkeypatch.setattr("src.services.llm.get_llm", lambda: FakeLLM())
    response = await client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        json={
            "client_message_id": "turn-vector-rag",
            "text": "What does the method report about review time?",
            "expected_report_version_id": version_id,
        },
    )

    assert response.status_code == 202, response.text
    assert seen == {
        "query": "What does the method report about review time?",
        "job_id": "job_rag_origin",
        "limit": "6",
    }
    message = response.json()["assistant_message"]
    assert message["content_scope"] == "conversation_report_rag"
    assert message["text"] == "The method reduces review time by streamlining its workflow."
    assert message["citations"][0]["paper_id"] == "W1"


@pytest.mark.asyncio
async def test_conversation_rag_asks_when_follow_up_has_multiple_entities(client, v2_isolated):
    repository, _, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    version = repository.create_report_version(project["project_id"], report_fixture(), "alice", "fixture")
    conversation = (
        await client.post(
            f"/api/v1/projects/{project['project_id']}/conversations",
            json={"initial_report_version_id": version["report_version_id"]},
        )
    ).json()["conversation"]
    repository.save_user_message(
        conversation["conversation_id"], "turn-compare", "So sánh RAG và LLM.", version["report_version_id"]
    )
    response = await client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        json={
            "client_message_id": "turn-ambiguous",
            "text": "Nó có tác dụng gì?",
            "expected_report_version_id": version["report_version_id"],
        },
    )

    message = response.json()["assistant_message"]
    assert message["message_type"] == "clarification"
    assert message["citations"] == []
    assert "RAG, LLM" in message["text"]


@pytest.mark.asyncio
async def test_empty_conversation_creation_is_idempotent(client, v2_isolated):
    repository, _, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    version = repository.create_report_version(project["project_id"], report_fixture(), "alice", "fixture")
    payload = {"initial_report_version_id": version["report_version_id"]}

    first = await client.post(f"/api/v1/projects/{project['project_id']}/conversations", json=payload)
    second = await client.post(f"/api/v1/projects/{project['project_id']}/conversations", json=payload)

    assert first.status_code == second.status_code == 201
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert first.json()["conversation"]["conversation_id"] == second.json()["conversation"]["conversation_id"]
    assert len(repository.list_conversations(project["project_id"], "alice")) == 1


@pytest.mark.asyncio
async def test_new_workspace_conversation_does_not_inherit_project_report(client, v2_isolated):
    repository, _, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    repository.create_report_version(project["project_id"], report_fixture(), "alice", "fixture")

    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/conversations",
        json={"initial_report_version_id": None, "force_new": True},
    )

    assert response.status_code == 201
    assert response.json()["conversation"]["active_report_version_id"] is None


@pytest.mark.asyncio
async def test_empty_project_returns_insufficient_evidence(client, v2_isolated):
    await login(client)
    project = await create_project(client)
    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/conversations", json={"initial_report_version_id": None}
    )
    conversation = response.json()["conversation"]
    response = await client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        json={"client_message_id": "turn-1", "text": "What are the findings?", "expected_report_version_id": None},
    )
    assert response.json()["assistant_message"]["message_type"] == "insufficient_evidence"
    assert response.json()["assistant_message"]["citations"] == []


@pytest.mark.asyncio
async def test_message_retry_is_idempotent_and_stale_context_is_blocked(client, v2_isolated):
    repository, _, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    version = repository.create_report_version(project["project_id"], report_fixture(), "alice", "fixture")
    conversation = (
        await client.post(
            f"/api/v1/projects/{project['project_id']}/conversations",
            json={"initial_report_version_id": version["report_version_id"]},
        )
    ).json()["conversation"]
    payload = {
        "client_message_id": "same-id",
        "text": "review time",
        "expected_report_version_id": version["report_version_id"],
    }
    first = await client.post(f"/api/v1/conversations/{conversation['conversation_id']}/messages", json=payload)
    second = await client.post(f"/api/v1/conversations/{conversation['conversation_id']}/messages", json=payload)
    assert first.status_code == second.status_code == 202
    assert second.json()["duplicate"] is True
    stale = await client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        json={**payload, "client_message_id": "new-id", "expected_report_version_id": "rv_stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "CONVERSATION_CONTEXT_STALE"


@pytest.mark.asyncio
async def test_memory_requires_confirmation_and_preserves_lineage(client, v2_isolated):
    await login(client)
    project = await create_project(client)
    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/memories",
        json={"memory_type": "hypothesis", "content": {"text": "A hypothesis, not a fact"}},
    )
    memory = response.json()["memory"]
    assert memory["status"] == "proposed"
    confirmed = await client.post(
        f"/api/v1/projects/{project['project_id']}/memories/{memory['memory_id']}/confirm", json={}
    )
    assert confirmed.json()["memory"]["status"] == "active"
    superseded = await client.post(
        f"/api/v1/projects/{project['project_id']}/memories/{memory['memory_id']}/supersede",
        json={"content": {"text": "Narrowed hypothesis"}, "evidence_ids": []},
    )
    assert superseded.status_code == 201
    assert superseded.json()["memory"]["supersedes_memory_id"] == memory["memory_id"]


@pytest.mark.asyncio
async def test_mutation_requires_confirmation_and_idempotency_key(client, v2_isolated):
    repository, _, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    version = repository.create_report_version(project["project_id"], report_fixture(), "alice", "fixture")
    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/action-proposals",
        json={
            "base_report_version_id": version["report_version_id"],
            "action_type": "discard_claim",
            "parameters": {"claim_id": "c1", "reason": "unsupported"},
            "reason": "Remove unsupported claim",
            "acceptance_criteria": ["Claim lineage remains auditable"],
            "estimated_impact": {
                "summary": "Discard one claim",
                "affected_paper_ids": [],
                "affected_claim_ids": ["c1"],
                "affected_gap_ids": [],
                "may_change_corpus": False,
                "requires_revalidation": True,
                "expected_new_papers_min": 0,
                "expected_new_papers_max": 0,
                "cost_class": "low",
            },
        },
    )
    action = response.json()["action"]
    assert action["status"] == "proposed"
    missing_key = await client.post(
        f"/api/v1/action-proposals/{action['action_id']}/approve",
        json={"expected_status": "proposed", "expected_base_report_version_id": version["report_version_id"]},
    )
    assert missing_key.status_code == 400
    approved = await client.post(
        f"/api/v1/action-proposals/{action['action_id']}/approve",
        headers={"Idempotency-Key": "stable-key"},
        json={"expected_status": "proposed", "expected_base_report_version_id": version["report_version_id"]},
    )
    assert approved.status_code == 202
    assert approved.json()["action"]["approved_by"] == "alice"


@pytest.mark.asyncio
async def test_action_parameters_are_discriminated(client, v2_isolated):
    await login(client)
    project = await create_project(client)
    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/action-proposals",
        json={
            "action_type": "search_more",
            "parameters": {"claim_id": "wrong-schema"},
            "reason": "bad",
            "acceptance_criteria": [],
            "estimated_impact": {
                "summary": "bad",
                "affected_paper_ids": [],
                "affected_claim_ids": [],
                "affected_gap_ids": [],
                "may_change_corpus": True,
                "requires_revalidation": True,
                "expected_new_papers_min": 0,
                "expected_new_papers_max": 1,
                "cost_class": "low",
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ACTION_PARAMETERS_INVALID"


@pytest.mark.asyncio
async def test_project_isolation_hides_resources(client, v2_isolated):
    await login(client, "researcher:alice")
    project = await create_project(client)
    await client.delete("/api/v1/auth/session")
    await login(client, "researcher:mallory")
    response = await client.get(f"/api/v1/projects/{project['project_id']}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_gap_requires_countersearch_and_creates_reviewer_feedback(client, v2_isolated):
    repository, _, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    job_id = "job_gap_review"
    repository.link_review_job(project["project_id"], job_id, "alice", "project_review", "Gap review", 10)
    version = repository.create_report_version(project["project_id"], report_fixture(), "alice", "fixture", job_id)
    repository.upsert_gaps_from_report(project["project_id"], version["report_version_id"], report_fixture())
    await client.post(
        f"/api/v1/projects/{project['project_id']}/members",
        json={"actor_id": "reviewer_demo", "project_role": "reviewer"},
    )
    _, invitation_token = repository.create_invitation(project["project_id"], job_id, "reviewer@example.com", "alice")
    repository.accept_invitation(invitation_token, "reviewer_demo")
    await client.delete("/api/v1/auth/session")
    await login(client, "reviewer:reviewer_demo")
    blocked = await client.post(
        "/api/v1/gaps/gap1/review",
        json={"report_version_id": version["report_version_id"], "verdict": "approve", "note": "looks good"},
    )
    assert blocked.status_code == 409
    repository.complete_gap_countersearch("gap1", version["report_version_id"], [])
    reviewed = await client.post(
        "/api/v1/gaps/gap1/review",
        json={"report_version_id": version["report_version_id"], "verdict": "approve", "note": "scoped correctly"},
    )
    assert reviewed.status_code == 201
    assert reviewed.json()["gap"]["status"] == "reviewer_approved"
    question = await client.get("/api/v1/gaps/gap1/research-question")
    assert question.status_code == 200
    await client.delete("/api/v1/auth/session")
    await login(client)
    feedback = await client.get(f"/api/v1/projects/{project['project_id']}/review-feedback")
    assert feedback.json()["items"][0]["target_id"] == "gap1"


@pytest.mark.asyncio
async def test_action_becomes_stale_when_report_version_changes(client, v2_isolated):
    repository, _, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    version = repository.create_report_version(project["project_id"], report_fixture(), "alice", "fixture")
    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/action-proposals",
        json={
            "base_report_version_id": version["report_version_id"],
            "action_type": "discard_claim",
            "parameters": {"claim_id": "c1", "reason": "unsupported"},
            "reason": "Remove unsupported claim",
            "acceptance_criteria": [],
            "estimated_impact": {
                "summary": "Discard claim",
                "affected_paper_ids": [],
                "affected_claim_ids": ["c1"],
                "affected_gap_ids": [],
                "may_change_corpus": False,
                "requires_revalidation": True,
                "expected_new_papers_min": 0,
                "expected_new_papers_max": 0,
                "cost_class": "low",
            },
        },
    )
    action = response.json()["action"]
    repository.create_report_version(project["project_id"], report_fixture(), "alice", "new evidence")
    stale = await client.post(
        f"/api/v1/action-proposals/{action['action_id']}/approve",
        headers={"Idempotency-Key": "stale-key"},
        json={"expected_status": "proposed", "expected_base_report_version_id": version["report_version_id"]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "ACTION_STALE"


@pytest.mark.asyncio
async def test_mvp2_metrics_observe_citation_policy(client, v2_isolated):
    repository, _, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    version = repository.create_report_version(project["project_id"], report_fixture(), "alice", "fixture")
    conversation = (
        await client.post(
            f"/api/v1/projects/{project['project_id']}/conversations",
            json={"initial_report_version_id": version["report_version_id"]},
        )
    ).json()["conversation"]
    await client.post(
        f"/api/v1/conversations/{conversation['conversation_id']}/messages",
        json={
            "client_message_id": "metrics-turn",
            "text": "review time",
            "expected_report_version_id": version["report_version_id"],
        },
    )
    response = await client.get("/api/v1/metrics/mvp2")
    assert response.status_code == 200
    assert response.json()["factual_answer_citation_coverage"] == 1.0
    assert response.json()["invalid_citations"] == 0


@pytest.mark.asyncio
async def test_project_review_uses_session_actor_and_creates_feedback(client, v2_isolated):
    repository, jobs, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    await client.post(
        f"/api/v1/projects/{project['project_id']}/members",
        json={"actor_id": "reviewer_demo", "project_role": "reviewer"},
    )
    job_id = "job_project_review"
    jobs.create_job(job_id, "alice", "researcher", "AI literature review", 10)
    repository.link_review_job(project["project_id"], job_id, "alice", "project_review")
    result = report_fixture()
    result["papers_count"] = 1
    jobs.complete_job(job_id, result)
    _, invitation_token = repository.create_invitation(project["project_id"], job_id, "reviewer@example.com", "alice")
    repository.accept_invitation(invitation_token, "reviewer_demo")
    await client.delete("/api/v1/auth/session")
    await login(client, "reviewer:reviewer_demo")
    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/reviews/{job_id}/review",
        json={
            "decisions": [{"claim_id": "c1", "verdict": "unsupported", "note": "Evidence is too narrow"}],
            "reference_checks": [],
            "report_decision": "request_changes",
            "report_note": "Please reground this claim",
        },
    )
    assert response.status_code == 202, response.text
    feedback = response.json()["feedback"]
    assert feedback[0]["target_id"] == "c1"
    assert feedback[0]["requested_action"] == "rerun_grounding"
    await client.delete("/api/v1/auth/session")
    await login(client)
    stored = await client.get(f"/api/v1/projects/{project['project_id']}/review-feedback")
    assert stored.json()["items"][0]["report_version_id"]


@pytest.mark.asyncio
async def test_invitation_assigns_only_the_target_review(client, v2_isolated, monkeypatch):
    repository, jobs, _ = v2_isolated
    await login(client)
    project = await create_project(client)
    job_id = "job_invited_review"
    jobs.create_job(job_id, "alice", "researcher", "Review invitation", 10)
    repository.link_review_job(project["project_id"], job_id, "alice", "project_review", "Review invitation", 10)
    # Patch email service before the first invitation POST so the result is
    # deterministic regardless of whether RESEND_API_KEY is set in .env.
    monkeypatch.setattr(
        v2_routes.invitation_email_service,
        "send_review_invitation",
        AsyncMock(return_value=SimpleNamespace(status="not_configured", provider_id=None, error=None)),
    )
    invited = await client.post(
        f"/api/v1/projects/{project['project_id']}/reviews/{job_id}/invitations",
        json={"email": "bob@example.com", "expires_in_days": 7},
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["invitation"]["email_delivery_status"] == "not_configured"
    old_token = invited.json()["invitation_url"].split("invitation=", 1)[1]
    monkeypatch.setattr(
        v2_routes,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="development",
            resend_api_key="re_test",
            resend_from_email="Review <review@example.com>",
            invitation_base_url="http://localhost:3000/",
            resend_min_interval_seconds=60,
        ),
    )
    monkeypatch.setattr(
        v2_routes.invitation_email_service,
        "send_review_invitation",
        AsyncMock(return_value=SimpleNamespace(status="sent", provider_id="email_123", error=None)),
    )
    resent = await client.post(
        f"/api/v1/projects/{project['project_id']}/invitations/{invited.json()['invitation']['invitation_id']}/resend"
    )
    assert resent.status_code == 200, resent.text
    assert resent.json()["invitation"]["email_delivery_status"] == "sent"
    assert resent.json()["invitation"]["resend_email_id"] == "email_123"
    token = resent.json()["invitation_url"].split("invitation=", 1)[1]
    obsolete = await client.get(f"/api/v1/invitations/{old_token}")
    assert obsolete.status_code == 404
    await client.delete("/api/v1/auth/session")
    await login(client, "researcher:bob")
    accepted = await client.post("/api/v1/invitations/accept", json={"token": token})
    assert accepted.status_code == 201, accepted.text
    assignments = await client.get("/api/v1/review-assignments")
    assert assignments.json()["items"][0]["job_id"] == job_id
    projects = await client.get("/api/v1/projects")
    assert projects.json()["items"][0]["project_role"] == "reviewer"
    chat = await client.post(
        f"/api/v1/projects/{project['project_id']}/conversations",
        json={"initial_report_version_id": None},
    )
    assert chat.status_code == 403


@pytest.mark.asyncio
async def test_project_review_allows_and_labels_self_review(client, v2_isolated):
    repository, jobs, _ = v2_isolated
    await login(client, "reviewer:alice")
    project = repository.create_project("alice", "Self-review project", "")
    repository.add_member(project["project_id"], "alice", "reviewer")
    job_id = "job_self_review"
    jobs.create_job(job_id, "alice", "researcher", "AI literature review", 10)
    repository.link_review_job(project["project_id"], job_id, "alice", "project_review")
    result = report_fixture()
    result["papers_count"] = 1
    jobs.complete_job(job_id, result)
    response = await client.post(
        f"/api/v1/projects/{project['project_id']}/reviews/{job_id}/review",
        json={
            "decisions": [{"claim_id": "c1", "verdict": "supported", "note": ""}],
            "reference_checks": [{"paper_id": "W1", "verdict": "valid", "note": ""}],
            "report_decision": "approve",
            "report_note": "Author verification",
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["submission"]["review_type"] == "self_review"
    assert response.json()["submission"]["decision"] == "approve"
    assert response.json()["submission"]["decisions"][0]["claim_id"] == "c1"
    assert response.json()["submission"]["reference_checks"][0]["paper_id"] == "W1"


@pytest.mark.asyncio
async def test_revise_action_regrounds_before_creating_version(v2_isolated, monkeypatch):
    repository, _, service = v2_isolated
    repository.create_session("researcher:alice")
    project = repository.create_project("alice", "Reground project", "")
    version = repository.create_report_version(project["project_id"], report_fixture(), "alice", "fixture")
    action = repository.create_action(
        {
            "project_id": project["project_id"],
            "base_report_version_id": version["report_version_id"],
            "action_type": "revise_claim",
            "parameters": {"claim_id": "c1", "proposed_text": "A narrower supported claim.", "reason": "review"},
            "reason": "Reviewer requested a narrower claim",
            "acceptance_criteria": ["Reground before versioning"],
            "estimated_impact": {
                "summary": "Revise one claim",
                "affected_paper_ids": ["W1"],
                "affected_claim_ids": ["c1"],
                "affected_gap_ids": [],
                "may_change_corpus": False,
                "requires_revalidation": True,
                "expected_new_papers_min": 0,
                "expected_new_papers_max": 0,
                "cost_class": "low",
            },
            "proposed_by": "alice",
        }
    )
    repository.decide_action(
        action["action_id"],
        "alice",
        "approved",
        "revise-key",
        {"expected_status": "proposed", "expected_base_report_version_id": version["report_version_id"]},
    )
    grounded = report_fixture()["claims"][0]
    grounded["text"] = "A narrower supported claim."
    monkeypatch.setattr(v2_service_module, "validate_grounding_node", AsyncMock(return_value={"claims": [grounded]}))
    await service.execute_action(action["action_id"])
    await asyncio.gather(*tuple(service._background_tasks))
    completed = repository.get_action(action["action_id"])
    assert completed["status"] == "completed"
    new_version = repository.get_report_version(project["project_id"], completed["result_report_version_id"])
    assert new_version["report"]["claims"][0]["text"] == "A narrower supported claim."
    assert new_version["report"]["revision_log"][0]["previous_text"] == "The method reduces review time."
