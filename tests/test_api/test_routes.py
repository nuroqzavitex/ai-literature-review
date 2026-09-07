from unittest.mock import AsyncMock

import pytest

from src.agents.litreview.infrastructure.repositories.jobs import JobRepository
from src.api.routers import literature_reviews as routes


@pytest.fixture
def isolated_repository(tmp_path, monkeypatch):
    repository = JobRepository(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(routes, "repository", repository)
    monkeypatch.setattr(routes.job_service, "repository", repository)
    monkeypatch.setattr(routes.job_service, "run", AsyncMock())
    monkeypatch.setattr(routes.job_service, "resume", AsyncMock())
    return repository


def completed_result() -> dict:
    paper = {
        "paper_id": "W001",
        "title": "Grounded paper",
        "authors": ["Researcher"],
        "year": 2024,
        "doi": None,
        "url": "https://openalex.org/W001",
        "abstract": "A grounded abstract with enough information for the API contract.",
        "cited_by_count": 10,
        "is_open_access": True,
        "relevance_score": 0.92,
        "rank": 1,
    }
    claim = {
        "claim_id": "claim_1",
        "claim_type": "contribution",
        "text": "The paper reports a grounded result.",
        "supporting_paper_ids": ["W001"],
        "evidence": [
            {
                "paper_id": "W001",
                "quote": "A grounded abstract",
                "section": "abstract",
            }
        ],
        "validation_status": "valid",
        "validation_errors": [],
    }
    return {
        "original_topic": "Grounded AI",
        "search_query": "Grounded AI",
        "query_history": ["Grounded AI"],
        "papers": [paper],
        "claims": [claim],
        "evidence_rows": [
            {
                "paper_id": "W001",
                "citation_label": "Researcher (2024)",
                "title": "Grounded paper",
                "year": 2024,
                "url": "https://openalex.org/W001",
                "method_claim_id": None,
                "dataset_claim_id": None,
                "contribution_claim_id": "claim_1",
                "limitation_claim_id": None,
            }
        ],
        "themes": [],
        "potential_gaps": [],
        "references": [
            {
                "paper_id": "W001",
                "title": "Grounded paper",
                "authors": ["Researcher"],
                "year": 2024,
                "doi": None,
                "url": "https://openalex.org/W001",
                "source": "openalex",
                "metadata_valid": True,
            }
        ],
        "scope_disclaimer": "Dựa trên 1 bài và đang chờ Reviewer xác nhận.",
        "decision_trace": [
            {
                "decision_id": "decision_1",
                "node": "validate_grounding",
                "action": "wait_for_human",
                "reason": "Claim đã vượt validation.",
                "created_at": "2026-07-29T00:00:00+00:00",
            }
        ],
        "revision_log": [],
        "source_warnings": [],
        "validation_warnings": [],
        "search_attempt": 1,
        "grounding_revision_attempt": 0,
        "review_revision_attempt": 0,
        "papers_count": 1,
    }


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "litreview-agent"


@pytest.mark.asyncio
async def test_agent_status_exposes_route_without_credentials(client, monkeypatch):
    class TestSettings:
        llm_failover_enabled = True

    monkeypatch.setattr(routes, "get_settings", TestSettings)
    monkeypatch.setattr(
        routes,
        "get_llm_route_status",
        lambda: [
            {"provider": "google", "model": "gemini-test"},
            {"provider": "openrouter", "model": "provider/model"},
        ],
    )

    response = await client.get("/api/v1/status")

    assert response.status_code == 200
    assert response.json() == {
        "status": "configured",
        "agent": "LitReview LangGraph MVP",
        "providers": [
            {"provider": "google", "model": "gemini-test"},
            {"provider": "openrouter", "model": "provider/model"},
        ],
        "failover_enabled": True,
        "runtime_verified": False,
        "detail": (
            "Provider configuration is complete. Runtime quota and connectivity "
            "are verified only when a review invokes the provider."
        ),
    }
    assert "key" not in response.text.lower()


@pytest.mark.asyncio
async def test_create_job_and_poll_status(client, isolated_repository):
    response = await client.post(
        "/api/v1/reviews",
        json={
            "topic": "Graph neural networks in drug discovery",
            "max_results": 10,
            "user_id": "researcher_1",
            "role": "researcher",
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["thread_id"] == payload["job_id"]
    assert payload["status"] == "queued"

    run_call = routes.job_service.run.await_args
    assert run_call is not None
    initial_state = run_call.args[1]
    assert initial_state["original_topic"] == "Graph neural networks in drug discovery"
    assert "topic" not in initial_state

    status_response = await client.get(f"/api/v1/reviews/{payload['job_id']}/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_reviewer_only_endpoints_enforce_role(client, isolated_repository):
    create_response = await client.post(
        "/api/v1/reviews",
        json={
            "topic": "A valid research topic",
            "max_results": 10,
            "user_id": "reviewer_1",
            "role": "reviewer",
        },
    )
    assert create_response.status_code == 403
    list_response = await client.get("/api/v1/reviews?role=researcher")
    assert list_response.status_code == 403


@pytest.mark.asyncio
async def test_result_uses_claim_based_contract_without_legacy_markdown(
    client,
    isolated_repository,
):
    repository = isolated_repository
    repository.create_job("job_1", "researcher_1", "researcher", "Grounded AI", 10)
    repository.complete_job("job_1", completed_result())

    response = await client.get("/api/v1/reviews/job_1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["claims"][0]["claim_id"] == "claim_1"
    assert payload["evidence_rows"][0]["contribution_claim_id"] == "claim_1"
    assert payload["references"][0]["metadata_valid"] is True
    assert payload["papers"][0]["rank"] == 1
    assert payload["papers"][0]["relevance_score"] == 0.92
    assert payload["original_topic"] == "Grounded AI"
    assert payload["search_query"] == "Grounded AI"
    assert payload["query_history"] == ["Grounded AI"]
    assert payload["revision_log"] == []
    assert payload["review_summary"]["total_claims"] == 1
    assert "comparison_matrix_md" not in payload
    assert "research_gap_report_md" not in payload
    assert "papers_summary" not in payload


@pytest.mark.asyncio
async def test_reviewer_can_review_claims_and_references(
    client,
    isolated_repository,
):
    repository = isolated_repository
    repository.create_job("job_1", "researcher_1", "researcher", "Grounded AI", 10)
    repository.complete_job("job_1", completed_result())

    response = await client.post(
        "/api/v1/reviews/job_1/review",
        json={
            "reviewer_id": "reviewer_1",
            "role": "reviewer",
            "decisions": [
                {
                    "claim_id": "claim_1",
                    "verdict": "supported",
                    "note": "Evidence hỗ trợ trực tiếp.",
                }
            ],
            "reference_checks": [
                {
                    "paper_id": "W001",
                    "verdict": "valid",
                    "note": "Metadata khớp OpenAlex.",
                }
            ],
            "report_decision": "approve",
            "report_note": "Đã đối chiếu.",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "resuming"
    assert response.json()["claim_support_accuracy"] == 1.0
    assert response.json()["reference_validity"] == 1.0

    repository.update_status("job_1", "approved")
    result = await client.get("/api/v1/reviews/job_1")
    assert result.status_code == 200
    assert result.json()["review_summary"] == {
        "total_claims": 1,
        "reviewed_claims": 1,
        "supported_claims": 1,
        "unsupported_claims": 0,
    }
    assert result.json()["review"] == {
        "reviewer_id": "reviewer_1",
        "report_decision": "approve",
        "report_note": "Đã đối chiếu.",
        "reviewed_at": result.json()["review"]["reviewed_at"],
        "decisions": [
            {
                "claim_id": "claim_1",
                "verdict": "supported",
                "note": "Evidence hỗ trợ trực tiếp.",
            }
        ],
        "reference_checks": [
            {
                "paper_id": "W001",
                "verdict": "valid",
                "note": "Metadata khớp OpenAlex.",
            }
        ],
    }


@pytest.mark.asyncio
async def test_research_gap_approval_does_not_resume_litreview_graph(
    client,
    isolated_repository,
    monkeypatch,
):
    repository = isolated_repository
    result = completed_result()
    result.update({"workflow_type": "research_gap", "intent": "research_gap", "claims": []})
    repository.create_job(
        "gap_job",
        "researcher_1",
        "researcher",
        "Grounded AI",
        10,
        workflow_type="research_gap",
    )
    repository.complete_job("gap_job", result)
    repository.update_status("gap_job", "approved")

    class Notifier:
        async def notify(self, *_args):
            raise AssertionError("Research-gap approval must not enqueue a Lit Review resume")

    monkeypatch.setattr(routes, "get_job_notifier", lambda: Notifier())
    response = await client.post(
        "/api/v1/reviews/gap_job/review",
        json={
            "reviewer_id": "reviewer_1",
            "role": "reviewer",
            "decisions": [],
            "reference_checks": [{"paper_id": "W001", "verdict": "valid", "note": ""}],
            "report_decision": "approve",
            "report_note": "Approved.",
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "approved"
    assert repository.get_status("gap_job")["status"] == "approved"


@pytest.mark.asyncio
async def test_cancel_review_allows_error_state_and_marks_job_cancelled(
    client,
    isolated_repository,
    monkeypatch,
):
    repository = isolated_repository
    repository.create_job("job_1", "researcher_1", "researcher", "Grounded AI", 10)
    repository.fail_job("job_1", "Embedding screening failed")

    class FakeV2Repository:
        def __init__(self) -> None:
            self.updated = None
            self.audited = None

        def project_for_job(self, job_id: str):
            assert job_id == "job_1"
            return {
                "project_id": "project_1",
                "status": "error",
                "requested_by": "researcher_1",
            }

        def update_review_status(self, job_id: str, status: str):
            self.updated = (job_id, status)
            return {"job_id": job_id, "status": status}

        def audit(self, *args):
            self.audited = args

    fake_v2_repository = FakeV2Repository()
    monkeypatch.setattr(routes, "v1_repository", repository)
    monkeypatch.setattr(routes, "v2_repository", fake_v2_repository)
    monkeypatch.setattr(routes.v2_service, "require_membership", lambda *_args, **_kwargs: {"project_role": "owner"})

    response = await client.post("/api/v1/projects/project_1/reviews/job_1/cancel")

    assert response.status_code == 200
    assert response.json() == {"job_id": "job_1", "status": "cancelled"}
    assert fake_v2_repository.updated == ("job_1", "cancelled")

    status_response = await client.get("/api/v1/reviews/job_1/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "cancelled"
    assert status_response.json()["current_node"] == "cancelled"


@pytest.mark.asyncio
async def test_live_status_exposes_progress_snapshot(client, isolated_repository):
    repository = isolated_repository
    repository.create_job("job_progress", "researcher_1", "researcher", "Grounded AI", 10)
    repository.update_progress(
        "job_progress",
        "validate_grounding",
        14,
        {
            "valid_claims": 3,
            "search_attempt": 1,
            "grounding_revision_attempt": 1,
            "search_query": "Grounded AI",
            "query_history": ["Grounded AI"],
            "last_decision": {"action": "revise_claims", "reason": "One claim needs revision."},
            "warnings": ["A validation warning"],
        },
    )

    response = await client.get("/api/v1/reviews/job_progress/status")

    assert response.status_code == 200
    assert response.json()["valid_claims"] == 3
    assert response.json()["search_attempt"] == 1
    assert response.json()["grounding_revision_attempt"] == 1
    assert response.json()["search_query"] == "Grounded AI"
    assert response.json()["last_decision"]["action"] == "revise_claims"
    assert response.json()["warnings"] == ["A validation warning"]


@pytest.mark.asyncio
async def test_reviewer_queue_can_filter_hitl_jobs(client, isolated_repository):
    repository = isolated_repository
    repository.create_job("job_waiting", "researcher_1", "researcher", "Waiting", 10)
    repository.complete_job("job_waiting", completed_result())
    repository.create_job("job_error", "researcher_2", "researcher", "Error", 10)
    repository.fail_job("job_error", "failed")

    response = await client.get("/api/v1/reviews?role=reviewer&status=hitl_waiting")

    assert response.status_code == 200
    assert [item["job_id"] for item in response.json()] == ["job_waiting"]


@pytest.mark.asyncio
async def test_saved_evaluation_can_be_loaded(client, isolated_repository):
    repository = isolated_repository
    repository.create_job("job_eval", "researcher_1", "researcher", "Evaluation", 10)
    repository.complete_job("job_eval", completed_result())
    repository.save_review(
        "job_eval",
        "reviewer_1",
        [{"claim_id": "claim_1", "verdict": "supported", "note": "OK"}],
        [{"paper_id": "W001", "verdict": "valid", "note": "OK"}],
        "approve",
        "Approved",
    )
    repository.update_status("job_eval", "approved")
    repository.save_evaluation("job_eval", "reviewer_1", 120, 20, 4.5, "Useful")

    response = await client.get("/api/v1/reviews/job_eval/evaluation")

    assert response.status_code == 200
    assert response.json()["manual_minutes"] == 120
    assert response.json()["mvp_minutes"] == 20
    assert response.json()["usefulness_score"] == 4.5
