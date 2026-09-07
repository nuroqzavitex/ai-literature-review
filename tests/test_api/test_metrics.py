"""Integration tests for metrics, evaluation, and gap validation.

Covers:
- save_evaluation with new schema fields
- get_mvp_metrics computed values
- mvp_passed=false when coverage < 1.0
- gap absolute-wording rejection
"""

import json

import pytest

from src.agents.litreview.infrastructure.repositories.jobs import JobRepository
from src.validation.grounding import check_absolute_wording


@pytest.fixture()
def repo(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    r = JobRepository(database_url=db_url)
    # Seed a user, job, and report (approved, with completed review)
    with r._write_lock, r._connect() as conn:
        conn.execute("INSERT INTO users(id, role, created_at) VALUES ('u1', 'researcher', '2026-01-01T00:00:00')")
        conn.execute(
            """INSERT INTO review_jobs(id, user_id, topic, max_results, status, current_node, papers_found, created_at)
               VALUES ('j1', 'u1', 'AI', 10, 'approved', 'finalize', 3, '2026-01-01T00:00:00')"""
        )
        report = {
            "claims": [
                {"claim_id": "c1", "claim_type": "contribution", "text": "T1"},
                {"claim_id": "c2", "claim_type": "method", "text": "T2"},
            ],
            "references": [
                {"paper_id": "p1"},
                {"paper_id": "p2"},
            ],
        }
        conn.execute(
            "INSERT INTO review_reports(job_id, result_json, hitl_approved, created_at) VALUES ('j1', ?, 1, '2026-01-01T00:00:00')",
            (json.dumps(report),),
        )
        # Seed reviewer and report_reviews so metrics JOIN works
        conn.execute("INSERT INTO users(id, role, created_at) VALUES ('r1', 'reviewer', '2026-01-01T00:00:00')")
        conn.execute(
            "INSERT INTO report_reviews(job_id, reviewer_id, decision, note, reviewed_at) "
            "VALUES ('j1', 'r1', 'approve', '', '2026-01-01T00:00:00')"
        )
    return r


class TestSaveEvaluation:
    def test_save_and_get(self, repo):
        result = repo.save_evaluation(
            job_id="j1",
            evaluator_id="e1",
            manual_minutes=120.0,
            mvp_minutes=20.0,
            usefulness_score=4.0,
            notes="Good",
        )
        assert result is not None
        assert result["manual_minutes"] == 120.0
        assert result["mvp_minutes"] == 20.0
        assert result["usefulness_score"] == 4.0

    def test_returns_none_for_missing_job(self, repo):
        result = repo.save_evaluation(
            job_id="nonexistent",
            evaluator_id="e1",
            manual_minutes=100.0,
            mvp_minutes=10.0,
            usefulness_score=3.0,
            notes="",
        )
        assert result is None


class TestMvpMetrics:
    def test_empty_state(self, repo):
        metrics = repo.get_mvp_metrics()
        assert metrics["reports_evaluated"] == 0
        assert metrics["mvp_passed"] is False
        assert metrics["claim_review_coverage"] == 0.0
        assert metrics["reference_review_coverage"] == 0.0

    def test_incomplete_review_coverage_fails(self, repo):
        # Review only 1 of 2 claims, check only 1 of 2 references
        with repo._write_lock, repo._connect() as conn:
            conn.execute(
                "INSERT INTO review_decisions(job_id, reviewer_id, claim_id, verdict, reviewed_at) VALUES ('j1', 'r1', 'c1', 'supported', '2026-01-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO reference_checks(job_id, reviewer_id, paper_id, verdict, checked_at) VALUES ('j1', 'r1', 'p1', 'valid', '2026-01-01T00:00:00')"
            )
        metrics = repo.get_mvp_metrics()
        assert metrics["claim_review_coverage"] == 0.5
        assert metrics["reference_review_coverage"] == 0.5
        assert metrics["mvp_passed"] is False

    def test_full_coverage_with_enough_data(self, repo):
        """Even with full coverage, mvp_passed is false if < 30 claims reviewed."""
        with repo._write_lock, repo._connect() as conn:
            conn.execute(
                "INSERT INTO review_decisions(job_id, reviewer_id, claim_id, verdict, reviewed_at) VALUES ('j1', 'r1', 'c1', 'supported', '2026-01-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO review_decisions(job_id, reviewer_id, claim_id, verdict, reviewed_at) VALUES ('j1', 'r1', 'c2', 'supported', '2026-01-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO reference_checks(job_id, reviewer_id, paper_id, verdict, checked_at) VALUES ('j1', 'r1', 'p1', 'valid', '2026-01-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO reference_checks(job_id, reviewer_id, paper_id, verdict, checked_at) VALUES ('j1', 'r1', 'p2', 'valid', '2026-01-01T00:00:00')"
            )
        metrics = repo.get_mvp_metrics()
        assert metrics["claim_review_coverage"] == 1.0
        assert metrics["reference_review_coverage"] == 1.0
        # Still fails because < 30 reviewed claims and < 5 evaluations
        assert metrics["mvp_passed"] is False

    def test_median_time_reduction(self, repo):
        repo.save_evaluation("j1", "e1", 100.0, 50.0, 4.0, "")
        metrics = repo.get_mvp_metrics()
        assert metrics["median_time_reduction"] == 0.5


class TestAbsoluteGapWording:
    def test_reject_no_study_has_ever(self):
        result = check_absolute_wording("No study has ever examined this.")
        assert result is not None

    def test_reject_never_been_researched(self):
        result = check_absolute_wording("This has never been researched.")
        assert result is not None

    def test_accept_scoped_wording(self):
        result = check_absolute_wording(
            'Trong 12 bài thu thập từ OpenAlex cho truy vấn "AI", chưa thấy scalability được đề cập.'
        )
        assert result is None
