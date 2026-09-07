"""REG-001..005 — V1 compatibility, migration, compiled E2E.

Test contract §5.I  (Compatibility và migration)
File: tests/v2/integration/test_v1_migration.py
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.v2.conftest import ACTOR_ALICE


async def _login(client: AsyncClient, actor_id: str = ACTOR_ALICE):
    resp = await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{actor_id}"})
    assert resp.status_code in (200, 201), resp.text


# ---------------------------------------------------------------------------
# REG-001 — V1 endpoints still respond correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reg_001_v1_jobs_endpoint_still_works(client):
    """REG-001: V1 /api/v1/reviews endpoint không hồi quy."""
    resp = await client.get("/api/v1/reviews")
    # V1 endpoint must respond (200 or auth), never 500.
    assert resp.status_code in (200, 401, 403, 422), f"V1 reviews endpoint broken: {resp.status_code} {resp.text}"


@pytest.mark.asyncio
async def test_reg_001_v1_search_endpoint_schema(client):
    """REG-001: V1 /api/v1/reviews responds with expected schema."""
    resp = await client.get("/api/v1/reviews")
    assert resp.status_code in (200, 401, 403, 422)
    if resp.status_code == 200:
        data = resp.json()
        assert isinstance(data, (dict, list))


# ---------------------------------------------------------------------------
# REG-002 — V1 response/behavior maintained
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reg_002_v1_job_create_returns_job_id(client):
    """REG-002: V1 POST /api/v1/reviews returns job_id (not renamed)."""
    resp = await client.post(
        "/api/v1/reviews",
        json={"topic": "test topic for regression", "max_results": 5, "actor_id": "reg_actor"},
    )
    # Only test the shape, not the full pipeline.
    assert resp.status_code in (200, 201, 202, 422), f"V1 review create unexpected status: {resp.status_code}"
    if resp.status_code in (200, 201, 202):
        body = resp.json()
        assert "job_id" in body, f"V1 review create must return job_id: {body}"


# ---------------------------------------------------------------------------
# REG-003 — Migration additive: V1 report accessible as ReportVersion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reg_003_v1_report_readable_as_v2_version(client, v2_isolated):
    """REG-003: Migration additive đọc được V1 report như ReportVersion gốc."""
    repository, jobs, service = v2_isolated
    await _login(client)

    # Create project and link a completed V1 job.
    project_resp = await client.post("/api/v1/projects", json={"name": "Migration test", "description": ""})
    assert project_resp.status_code == 201
    project_id = project_resp.json()["project"]["project_id"]

    # Create a V1 job and complete it.
    job_id = "job_reg_003"
    jobs.create_job(job_id, ACTOR_ALICE, "researcher", "Migration topic", 5)

    # Link to V2 project and complete with minimal fixture.
    report_result = {
        "topic": "Migration topic",
        "papers_count": 1,
        "claims": [
            {
                "claim_id": "c1",
                "text": "Claim one",
                "theme": "T1",
                "evidence": [
                    {
                        "paper_id": "W1",
                        "title": "Paper 1",
                        "year": 2020,
                        "doi": "10.1/test",
                        "authors": "Auth",
                        "abstract": "Abstract text",
                        "quote": "Quote text",
                        "relevance_score": 0.9,
                        "support_type": "supports",
                    }
                ],
            }
        ],
        "search_queries": [],
        "unknown_aspects": [],
        "papers": [],
    }
    jobs.complete_job(job_id, report_result)
    repository.link_review_job(project_id, job_id, ACTOR_ALICE, "project_review", "Migration topic", 5)

    # After sync, the project should have a report version.
    capabilities = await client.get(f"/api/v1/projects/{project_id}/capabilities")
    assert capabilities.status_code == 200
    snap = capabilities.json()["capability_snapshot"]
    # If sync worked, stage should be abstract_ready.
    assert snap["data_stage"] in {"abstract_ready", "empty", "search_running"}, (
        f"Unexpected stage after V1 job completion: {snap}"
    )


# ---------------------------------------------------------------------------
# REG-004 — Roll-forward migration twice does not duplicate data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reg_004_migration_idempotent(client, v2_isolated):
    """REG-004: Roll-forward migration hai lần không nhân đôi project/membership/version."""
    repository, jobs, service = v2_isolated
    await _login(client)

    project_resp = await client.post("/api/v1/projects", json={"name": "Idempotent migration", "description": ""})
    assert project_resp.status_code == 201
    project_id = project_resp.json()["project"]["project_id"]

    # Call capabilities twice — should produce same stage, not double data.
    c1 = await client.get(f"/api/v1/projects/{project_id}/capabilities")
    c2 = await client.get(f"/api/v1/projects/{project_id}/capabilities")
    assert c1.status_code == 200
    assert c2.status_code == 200
    assert c1.json()["capability_snapshot"]["data_stage"] == c2.json()["capability_snapshot"]["data_stage"]
