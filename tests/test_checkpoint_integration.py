from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from src.agents.litreview.application.jobs import LitReviewJobService
from src.agents.litreview.domain.models import AgentState
from src.agents.litreview.infrastructure.repositories.jobs import JobRepository


@pytest.fixture
def isolated_repository(tmp_path):
    repo = JobRepository(f"sqlite:///{tmp_path / 'test.db'}")
    return repo


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def create_dummy_graph():
    graph = StateGraph(AgentState)

    async def dummy_plan(state):
        return {"papers": [{"paper_id": "1"}], "synthesis_completed": True}

    async def dummy_human_review(state):
        try:
            resume_payload = interrupt({"job_id": "test"})
        except GraphInterrupt:
            raise
        except Exception:
            if state.get("hitl_decision"):
                resume_payload = state.get("hitl_decision")
            else:
                raise

        if isinstance(resume_payload, dict):
            hitl_decision = resume_payload.get("hitl_decision")
        else:
            hitl_decision = resume_payload

        return {"status": "hitl_waiting", "hitl_decision": hitl_decision}

    async def dummy_revise(state):
        return {"claim_revision_attempt": state.get("claim_revision_attempt", 0) + 1}

    async def dummy_finalize(state):
        return {"status": "approved"}

    async def dummy_error(state):
        raise ValueError("Simulated failure")

    graph.add_node("plan", dummy_plan)
    graph.add_node("human_review", dummy_human_review)
    graph.add_node("revise", dummy_revise)
    graph.add_node("finalize", dummy_finalize)
    graph.add_node("error", dummy_error)

    graph.set_entry_point("plan")

    def after_plan(state):
        return "human_review"

    def after_human_review(state):
        d = state.get("hitl_decision")
        if d == "approve":
            return "finalize"
        if d == "request_changes":
            return "revise"
        if d == "error":
            return "error"
        return END

    def after_revise(state):
        return "human_review"

    graph.add_conditional_edges("plan", after_plan)
    graph.add_conditional_edges("human_review", after_human_review)
    graph.add_conditional_edges("revise", after_revise)
    graph.add_edge("finalize", END)
    graph.add_edge("error", END)

    return graph


dummy_uncompiled_graph = create_dummy_graph()


@pytest.mark.asyncio
async def test_checkpoint_pause_and_resume_approve(tmp_cwd, isolated_repository):
    service = LitReviewJobService(repository=isolated_repository)
    job_id = "test_job_resume"
    isolated_repository.create_job(job_id, "researcher_1", "researcher", "query", 10)

    with patch("src.agents.litreview.application.jobs.uncompiled_graph", dummy_uncompiled_graph):
        await service.run(job_id, {"job_id": job_id, "query": "test"})

    status = isolated_repository.get_status(job_id)
    assert status["status"] == "hitl_waiting"

    service2 = LitReviewJobService(repository=isolated_repository)
    isolated_repository.update_status(job_id, "resuming")

    with patch("src.agents.litreview.application.jobs.uncompiled_graph", dummy_uncompiled_graph):
        await service2.resume(job_id, {"hitl_decision": "approve"})

    status = isolated_repository.get_status(job_id)
    assert status["status"] == "approved"


@pytest.mark.asyncio
async def test_checkpoint_resume_request_changes(tmp_cwd, isolated_repository):
    service = LitReviewJobService(repository=isolated_repository)
    job_id = "test_job_changes"
    isolated_repository.create_job(job_id, "researcher_1", "researcher", "query", 10)

    with patch("src.agents.litreview.application.jobs.uncompiled_graph", dummy_uncompiled_graph):
        await service.run(job_id, {"job_id": job_id, "query": "test"})

    status = isolated_repository.get_status(job_id)
    assert status["status"] == "hitl_waiting"

    isolated_repository.update_status(job_id, "resuming")

    with patch("src.agents.litreview.application.jobs.uncompiled_graph", dummy_uncompiled_graph):
        await service.resume(job_id, {"hitl_decision": "request_changes"})

    status = isolated_repository.get_status(job_id)
    assert status["status"] == "hitl_waiting"


@pytest.mark.asyncio
async def test_checkpoint_resume_error(tmp_cwd, isolated_repository):
    service = LitReviewJobService(repository=isolated_repository)
    job_id = "test_job_error"
    isolated_repository.create_job(job_id, "researcher_1", "researcher", "query", 10)

    with patch("src.agents.litreview.application.jobs.uncompiled_graph", dummy_uncompiled_graph):
        await service.run(job_id, {"job_id": job_id, "query": "test"})

    isolated_repository.update_status(job_id, "resuming")

    with patch("src.agents.litreview.application.jobs.uncompiled_graph", dummy_uncompiled_graph):
        await service.resume(job_id, {"hitl_decision": "error"})

    status = isolated_repository.get_status(job_id)
    assert status["status"] == "error"
    assert "Simulated failure" in status["error"]


# ─── Recovery lease tests ────────────────────────────────────────────────────


def test_get_resuming_jobs_claims_unclaimed(isolated_repository):
    """A freshly-resuming job with no claim stamp is immediately returned."""
    isolated_repository.create_job("j1", "u1", "researcher", "topic", 5)
    isolated_repository.update_status("j1", "resuming")
    # Manually insert a report_reviews row so payload can be built
    import sqlite3

    conn = sqlite3.connect(isolated_repository.path)
    conn.execute("INSERT INTO users(id,role,created_at) VALUES('r1','reviewer','2024-01-01T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO review_reports(job_id,result_json,created_at) VALUES('j1','{}','2024-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO report_reviews(job_id,reviewer_id,decision,note,reviewed_at) "
        "VALUES('j1','r1','approve','','2024-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    jobs = isolated_repository.get_resuming_jobs()
    assert len(jobs) == 1
    assert jobs[0][0] == "j1"


def test_get_resuming_jobs_skips_recently_claimed(isolated_repository):
    """A job claimed within the timeout window is not returned again."""
    isolated_repository.create_job("j2", "u2", "researcher", "topic", 5)
    isolated_repository.update_status("j2", "resuming")

    import sqlite3

    now = datetime.now(UTC).isoformat()
    conn = sqlite3.connect(isolated_repository.path)
    conn.execute("INSERT INTO users(id,role,created_at) VALUES('r2','reviewer','2024-01-01T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO review_reports(job_id,result_json,created_at) VALUES('j2','{}','2024-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO report_reviews(job_id,reviewer_id,decision,note,reviewed_at) "
        "VALUES('j2','r2','approve','','2024-01-01T00:00:00+00:00')"
    )
    # Simulate: job was already claimed 1 minute ago (within timeout)
    conn.execute("UPDATE review_jobs SET resume_claimed_at=? WHERE id='j2'", (now,))
    conn.commit()
    conn.close()

    jobs = isolated_repository.get_resuming_jobs()
    assert len(jobs) == 0


def test_get_resuming_jobs_reclaims_expired_lease(isolated_repository):
    """A job whose lease has expired (> timeout) is returned for recovery."""
    isolated_repository.create_job("j3", "u3", "researcher", "topic", 5)
    isolated_repository.update_status("j3", "resuming")

    import sqlite3

    # Simulate a claim that expired 10 minutes ago
    expired = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    conn = sqlite3.connect(isolated_repository.path)
    conn.execute("INSERT INTO users(id,role,created_at) VALUES('r3','reviewer','2024-01-01T00:00:00+00:00')")
    conn.execute(
        "INSERT INTO review_reports(job_id,result_json,created_at) VALUES('j3','{}','2024-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO report_reviews(job_id,reviewer_id,decision,note,reviewed_at) "
        "VALUES('j3','r3','approve','','2024-01-01T00:00:00+00:00')"
    )
    conn.execute("UPDATE review_jobs SET resume_claimed_at=? WHERE id='j3'", (expired,))
    conn.commit()
    conn.close()

    jobs = isolated_repository.get_resuming_jobs()
    assert len(jobs) == 1
    assert jobs[0][0] == "j3"


# ─── Multi-reviewer stats tests ──────────────────────────────────────────────


def test_review_summary_uses_only_latest_reviewer(isolated_repository):
    """get_review_summary must only count the authoritative (latest) reviewer's decisions."""
    import sqlite3

    isolated_repository.create_job("jm", "u1", "researcher", "topic", 5)

    now = datetime.now(UTC).isoformat()
    earlier = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    conn = sqlite3.connect(isolated_repository.path)
    # Insert both reviewers
    for uid in ("rev_a", "rev_b"):
        conn.execute(f"INSERT INTO users(id,role,created_at) VALUES('{uid}','reviewer','{now}')")
    conn.execute(
        f"INSERT INTO review_reports(job_id,result_json,created_at) "
        f"VALUES('jm','{{\"claims\":[{{\"claim_id\":\"c1\"}}]}}','{now}')"
    )
    # rev_a reviewed earlier and says "unsupported"
    conn.execute(
        f"INSERT INTO review_decisions(job_id,reviewer_id,claim_id,verdict,reviewed_at) "
        f"VALUES('jm','rev_a','c1','unsupported','{earlier}')"
    )
    # rev_b (latest) reviewed after and says "supported"
    conn.execute(
        f"INSERT INTO review_decisions(job_id,reviewer_id,claim_id,verdict,reviewed_at) "
        f"VALUES('jm','rev_b','c1','supported','{now}')"
    )
    # report_reviews points to rev_b as authoritative
    conn.execute(
        f"INSERT INTO report_reviews(job_id,reviewer_id,decision,note,reviewed_at) "
        f"VALUES('jm','rev_b','approve','','{now}')"
    )
    conn.commit()
    conn.close()

    summary = isolated_repository.get_review_summary("jm")
    # Only rev_b's verdict should be counted → 1 claim, 1 supported, 0 unsupported
    assert summary["total_claims"] == 1
    assert summary["reviewed_claims"] == 1
    assert summary["supported_claims"] == 1
    assert summary["unsupported_claims"] == 0


def test_evaluation_rejected_for_non_approved_job(isolated_repository):
    """save_evaluation must return None for jobs not in 'approved' status."""
    isolated_repository.create_job("je", "u1", "researcher", "topic", 5)
    # Job is still queued
    result = isolated_repository.save_evaluation("je", "eval_1", 120.0, 10.0, 4.5, "good")
    assert result is None
