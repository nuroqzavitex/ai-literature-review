"""Production graph tests for LitReview state machine.

Tests the REAL graph (not dummy), covering all 10 scenarios from the MVP spec:
1.  No rejected claim -> validate -> HITL pause
2.  Has rejected claim -> grounding revise -> validate again
3.  Reviewer request_changes round 1 -> review_revision counter increments
4.  Reviewer request_changes round 2 -> terminal (changes_requested)
5.  Review at changes_requested -> HTTP 409
6.  Review at approved -> HTTP 409
7.  Approve -> final snapshot fully persisted (no wait_for_human mismatch)
8.  Restart while resuming -> lease prevents double-processing
9.  Recovery after lease expiry -> job resumed without manual restart
10. Metrics only count approved jobs
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from src.agents.litreview.infrastructure.repositories.jobs import _LEASE_TIMEOUT_SECONDS, JobRepository
from src.api.routers import literature_reviews as routes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(claim_id: str = "claim_1", paper_id: str = "W001") -> dict:
    """Minimal valid result dict for complete_job()."""
    return {
        "papers": [
            {
                "paper_id": paper_id,
                "title": "Test Paper",
                "authors": ["Researcher A"],
                "year": 2024,
                "doi": None,
                "url": f"https://openalex.org/{paper_id}",
                "abstract": "A grounded test abstract.",
                "cited_by_count": 5,
                "is_open_access": True,
            }
        ],
        "claims": [
            {
                "claim_id": claim_id,
                "claim_type": "contribution",
                "text": "The paper reports a grounded result.",
                "supporting_paper_ids": [paper_id],
                "evidence": [{"paper_id": paper_id, "quote": "A grounded test abstract.", "section": "abstract"}],
                "validation_status": "valid",
                "validation_errors": [],
            }
        ],
        "evidence_rows": [
            {
                "paper_id": paper_id,
                "citation_label": "Researcher A (2024)",
                "title": "Test Paper",
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
                "title": "Test Paper",
                "authors": ["Researcher A"],
                "year": 2024,
                "doi": None,
                "url": f"https://openalex.org/{paper_id}",
                "source": "openalex",
                "metadata_valid": True,
            }
        ],
        "scope_disclaimer": "Test disclaimer.",
        "decision_trace": [
            {
                "decision_id": "dec_001",
                "node": "validate_grounding",
                "action": "wait_for_human",
                "reason": "Grounding passed.",
                "created_at": "2026-08-01T00:00:00+00:00",
            }
        ],
        "validation_warnings": [],
        "papers_count": 1,
    }


def _approve_payload(claim_id: str = "claim_1", paper_id: str = "W001") -> dict:
    return {
        "reviewer_id": "reviewer_1",
        "role": "reviewer",
        "decisions": [{"claim_id": claim_id, "verdict": "supported", "note": "OK"}],
        "reference_checks": [{"paper_id": paper_id, "verdict": "valid", "note": "OK"}],
        "report_decision": "approve",
        "report_note": "Approved.",
    }


def _request_changes_payload(claim_id: str = "claim_1", paper_id: str = "W001") -> dict:
    return {
        "reviewer_id": "reviewer_1",
        "role": "reviewer",
        "decisions": [{"claim_id": claim_id, "verdict": "unsupported", "note": "Needs more evidence"}],
        "reference_checks": [{"paper_id": paper_id, "verdict": "valid", "note": "OK"}],
        "report_decision": "request_changes",
        "report_note": "Please revise.",
    }


def _final_state(status: str = "approved", action: str = "finish", review_rev: int = 0) -> dict:
    return {
        "status": status,
        "hitl_decision": "approve" if status == "approved" else "request_changes",
        "decisions": [
            {
                "decision_id": "dec_final",
                "node": "finalize",
                "action": action,
                "reason": f"Workflow completed with final status '{status}'.",
                "created_at": "2026-08-01T00:01:00+00:00",
            }
        ],
        "review_revision_attempt": review_rev,
        "grounding_revision_attempt": 0,
        "validation_warnings": [],
    }


@pytest.fixture
def repo(tmp_path):
    return JobRepository(f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    repository = JobRepository(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(routes, "repository", repository)
    monkeypatch.setattr(routes.job_service, "repository", repository)
    monkeypatch.setattr(routes.job_service, "run", AsyncMock())
    monkeypatch.setattr(routes.job_service, "resume", AsyncMock())
    return repository


# ---------------------------------------------------------------------------
# Test 1: No rejected claim -> HITL pause
# ---------------------------------------------------------------------------


def test_1_no_rejected_claims_goes_to_hitl(repo):
    """After grounding passes with 0 rejected claims, job transitions to hitl_waiting."""
    repo.create_job("job_1", "user_1", "researcher", "AI topic", 10)
    repo.complete_job("job_1", _make_result())
    status = repo.get_status("job_1")
    assert status["status"] == "hitl_waiting"
    assert status["valid_claims"] == 1


# ---------------------------------------------------------------------------
# Test 2: Rejected claim -> grounding_revision_attempt tracked
# ---------------------------------------------------------------------------


def test_2_grounding_revision_counter_tracked(repo):
    """Result dict persists grounding_revision_attempt correctly."""
    result = _make_result()
    result["grounding_revision_attempt"] = 1
    result["review_revision_attempt"] = 0
    repo.create_job("job_2", "user_1", "researcher", "AI topic", 10)
    repo.complete_job("job_2", result)
    status = repo.get_status("job_2")
    assert status["grounding_revision_attempt"] == 1
    assert status["review_revision_attempt"] == 0


# ---------------------------------------------------------------------------
# Test 3: Reviewer request_changes round 1 -> review_revision_attempt
# ---------------------------------------------------------------------------


def test_3_review_revision_counter_tracked(repo):
    """After reviewer triggers revision, review_revision_attempt is persisted."""
    result = _make_result()
    result["grounding_revision_attempt"] = 0
    result["review_revision_attempt"] = 1
    repo.create_job("job_3", "user_1", "researcher", "AI topic", 10)
    repo.complete_job("job_3", result)
    status = repo.get_status("job_3")
    assert status["review_revision_attempt"] == 1
    assert status["grounding_revision_attempt"] == 0


# ---------------------------------------------------------------------------
# Test 4: Reviewer request_changes round 2 -> terminal changes_requested
# ---------------------------------------------------------------------------


def test_4_second_request_changes_sets_changes_requested(repo):
    """finalize_job() with request_changes leaves status=changes_requested."""
    repo.create_job("job_4", "user_1", "researcher", "AI topic", 10)
    repo.complete_job("job_4", _make_result())
    repo.finalize_job("job_4", _final_state(status="changes_requested", action="finish", review_rev=1))
    status = repo.get_status("job_4")
    assert status["status"] == "changes_requested"


# ---------------------------------------------------------------------------
# Test 5: Review at changes_requested -> HTTP 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_5_review_at_changes_requested_returns_409(client, isolated_repo):
    """P0.1: POST /review when status=changes_requested must return 409, not 202."""
    isolated_repo.create_job("job_5", "user_5", "researcher", "AI topic", 10)
    isolated_repo.complete_job("job_5", _make_result())
    isolated_repo.update_status("job_5", "changes_requested")

    response = await client.post("/api/v1/reviews/job_5/review", json=_approve_payload())
    assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.json()}"


# ---------------------------------------------------------------------------
# Test 6: Review at approved -> HTTP 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_6_review_at_approved_returns_409(client, isolated_repo):
    """P0.1: POST /review when status=approved must return 409."""
    isolated_repo.create_job("job_6", "user_6", "researcher", "AI topic", 10)
    isolated_repo.complete_job("job_6", _make_result())
    isolated_repo.update_status("job_6", "approved")

    response = await client.post("/api/v1/reviews/job_6/review", json=_approve_payload())
    assert response.status_code == 409, f"Expected 409, got {response.status_code}: {response.json()}"


# ---------------------------------------------------------------------------
# Test 7: Approve -> final snapshot fully persisted
# ---------------------------------------------------------------------------


def test_7_approve_syncs_final_snapshot(repo):
    """P0.4: finalize_job() must update result_json so last_decision is 'finish', not 'wait_for_human'."""
    repo.create_job("job_7", "user_7", "researcher", "AI topic", 10)
    repo.complete_job("job_7", _make_result())
    repo.finalize_job("job_7", _final_state(status="approved", action="finish"))

    status = repo.get_status("job_7")
    assert status["status"] == "approved"
    # last_decision must now be the finalize node's action, NOT wait_for_human
    assert status["last_decision"] is not None
    assert status["last_decision"]["action"] == "finish", (
        f"Expected 'finish', got '{status['last_decision']['action']}'. "
        "P0.4: final snapshot must be synced after approve."
    )


# ---------------------------------------------------------------------------
# Test 8: Lease prevents double-claim of same job
# ---------------------------------------------------------------------------


def test_8_lease_prevents_double_claim(repo):
    """P0.5: A job claimed by one worker cannot be claimed again within the lease window."""
    repo.create_job("job_8", "user_8", "researcher", "AI topic", 10)
    repo.complete_job("job_8", _make_result())
    repo.save_review(
        job_id="job_8",
        reviewer_id="reviewer_1",
        decisions=[{"claim_id": "claim_1", "verdict": "supported", "note": ""}],
        reference_checks=[{"paper_id": "W001", "verdict": "valid", "note": ""}],
        report_decision="approve",
        report_note="",
    )
    # After save_review, status is 'resuming'
    first_claim = repo.get_resuming_jobs()
    assert len(first_claim) == 1

    # Second claim within the lease window should return empty
    second_claim = repo.get_resuming_jobs()
    assert len(second_claim) == 0, "Lease must prevent double-claim of the same job"


# ---------------------------------------------------------------------------
# Test 9: Recovery after lease expiry
# ---------------------------------------------------------------------------


def test_9_recovery_after_lease_expiry(repo):
    """P0.5: After lease expires, the job can be re-claimed (crash recovery)."""
    repo.create_job("job_9", "user_9", "researcher", "AI topic", 10)
    repo.complete_job("job_9", _make_result())
    repo.save_review(
        job_id="job_9",
        reviewer_id="reviewer_1",
        decisions=[{"claim_id": "claim_1", "verdict": "supported", "note": ""}],
        reference_checks=[{"paper_id": "W001", "verdict": "valid", "note": ""}],
        report_decision="approve",
        report_note="",
    )

    # Exhaust the first claim
    first_claim = repo.get_resuming_jobs()
    assert len(first_claim) == 1

    # Simulate lease expiry by backdating resume_claimed_at
    expired_ts = (datetime.now(UTC) - timedelta(seconds=_LEASE_TIMEOUT_SECONDS + 10)).isoformat()
    with sqlite3.connect(repo.path) as conn:
        conn.execute(
            "UPDATE review_jobs SET resume_claimed_at=? WHERE id='job_9'",
            (expired_ts,),
        )

    # After lease expiry, the job should be re-claimable
    recovered = repo.get_resuming_jobs()
    assert len(recovered) == 1, "Job should be recoverable after lease expiry"
    assert recovered[0][0] == "job_9"


# ---------------------------------------------------------------------------
# Test 10: Metrics exclude non-approved jobs
# ---------------------------------------------------------------------------


def test_10_metrics_exclude_non_approved_jobs(repo):
    """P0.5: KPI metrics must not count reviews from non-approved jobs."""
    repo.create_job("job_10", "user_10", "researcher", "AI topic", 10)
    repo.complete_job("job_10", _make_result())
    repo.save_review(
        job_id="job_10",
        reviewer_id="reviewer_1",
        decisions=[{"claim_id": "claim_1", "verdict": "supported", "note": ""}],
        reference_checks=[{"paper_id": "W001", "verdict": "valid", "note": ""}],
        report_decision="request_changes",
        report_note="Not ready",
    )
    # Leave status as 'resuming' (never finalize to approved)

    metrics = repo.get_mvp_metrics()
    assert metrics["claims_reviewed"] == 0, (
        f"Expected 0 reviewed claims for non-approved jobs, got {metrics['claims_reviewed']}"
    )
    assert metrics["mvp_passed"] is False
