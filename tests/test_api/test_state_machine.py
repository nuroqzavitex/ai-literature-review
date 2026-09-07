"""State machine boundary tests — verifies HTTP 409 for all non-hitl_waiting statuses.

Covers P0.1: only hitl_waiting allows POST /review.
All other statuses (approved, changes_requested, queued, running, resuming, error)
must return 409.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.agents.litreview.infrastructure.repositories.jobs import JobRepository
from src.api.routers import literature_reviews as routes


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    repository = JobRepository(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(routes, "repository", repository)
    monkeypatch.setattr(routes.job_service, "repository", repository)
    monkeypatch.setattr(routes.job_service, "run", AsyncMock())
    monkeypatch.setattr(routes.job_service, "resume", AsyncMock())
    return repository


def _valid_result(claim_id: str = "claim_sm", paper_id: str = "W_SM") -> dict:
    return {
        "papers": [
            {
                "paper_id": paper_id,
                "title": "SM Paper",
                "authors": ["Author"],
                "year": 2024,
                "doi": None,
                "url": f"https://openalex.org/{paper_id}",
                "abstract": "State machine test abstract.",
                "cited_by_count": 1,
                "is_open_access": True,
            }
        ],
        "claims": [
            {
                "claim_id": claim_id,
                "claim_type": "contribution",
                "text": "Test claim.",
                "supporting_paper_ids": [paper_id],
                "evidence": [{"paper_id": paper_id, "quote": "State machine test abstract.", "section": "abstract"}],
                "validation_status": "valid",
                "validation_errors": [],
            }
        ],
        "evidence_rows": [
            {
                "paper_id": paper_id,
                "citation_label": "Author (2024)",
                "title": "SM Paper",
                "year": 2024,
                "url": f"https://openalex.org/{paper_id}",
                "method_claim_id": None,
                "dataset_claim_id": None,
                "contribution_claim_id": claim_id,
                "limitation_claim_id": None,
            }
        ],
        "themes": [],
        "potential_gaps": [],
        "references": [
            {
                "paper_id": paper_id,
                "title": "SM Paper",
                "authors": ["Author"],
                "year": 2024,
                "doi": None,
                "url": f"https://openalex.org/{paper_id}",
                "source": "openalex",
                "metadata_valid": True,
            }
        ],
        "scope_disclaimer": "SM test.",
        "decision_trace": [
            {
                "decision_id": "dec_sm",
                "node": "validate_grounding",
                "action": "wait_for_human",
                "reason": "Grounding passed.",
                "created_at": "2026-08-01T00:00:00+00:00",
            }
        ],
        "validation_warnings": [],
        "papers_count": 1,
    }


def _review_payload(claim_id: str = "claim_sm", paper_id: str = "W_SM") -> dict:
    return {
        "reviewer_id": "rev_sm",
        "role": "reviewer",
        "decisions": [{"claim_id": claim_id, "verdict": "supported", "note": "OK"}],
        "reference_checks": [{"paper_id": paper_id, "verdict": "valid", "note": "OK"}],
        "report_decision": "approve",
        "report_note": "OK",
    }


TERMINAL_OR_NON_REVIEWABLE = [
    "approved",
    "changes_requested",
    "error",
    "queued",
    "running",
    "resuming",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_status", TERMINAL_OR_NON_REVIEWABLE)
async def test_review_rejected_for_non_hitl_waiting_status(client, isolated_repo, bad_status):
    """P0.1: POST /review must return 409 for all statuses other than hitl_waiting."""
    repo = isolated_repo
    repo.create_job(f"job_sm_{bad_status}", "user_sm", "researcher", "AI topic", 10)
    repo.complete_job(f"job_sm_{bad_status}", _valid_result())
    # Override to the status under test
    repo.update_status(f"job_sm_{bad_status}", bad_status)

    response = await client.post(
        f"/api/v1/reviews/job_sm_{bad_status}/review",
        json=_review_payload(),
    )
    assert response.status_code == 409, (
        f"Status '{bad_status}': expected 409, got {response.status_code}. Only hitl_waiting should allow review."
    )


@pytest.mark.asyncio
async def test_review_accepted_only_at_hitl_waiting(client, isolated_repo):
    """Verify the positive case: review IS accepted when status=hitl_waiting."""
    repo = isolated_repo
    repo.create_job("job_sm_ok", "user_sm_ok", "researcher", "AI topic", 10)
    repo.complete_job("job_sm_ok", _valid_result())
    # Status is hitl_waiting after complete_job

    response = await client.post(
        "/api/v1/reviews/job_sm_ok/review",
        json=_review_payload(),
    )
    assert response.status_code == 202, f"Expected 202 at hitl_waiting, got {response.status_code}: {response.json()}"
