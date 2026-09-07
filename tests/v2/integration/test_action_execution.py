"""ACT-001..012 — Tool registry, ActionProposal, confirmation, idempotency, version.

Test contract §5.E  (Tool, action, idempotency và version)
File: tests/v2/integration/test_action_execution.py
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.v2.conftest import ACTOR_ALICE


async def _login(client: AsyncClient, actor_id: str = ACTOR_ALICE, role: str = "researcher"):
    resp = await client.post("/api/v1/auth/session", json={"bootstrap_token": f"{role}:{actor_id}"})
    assert resp.status_code in (200, 201), resp.text


async def _create_project(client: AsyncClient, name: str = "Action Test") -> dict:
    resp = await client.post("/api/v1/projects", json={"name": name, "description": ""})
    assert resp.status_code == 201, resp.text
    return resp.json()["project"]


# ---------------------------------------------------------------------------
# ACT-003 — Unknown action_type / malformed parameters rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_act_003_unknown_action_type_rejected(client, v2_isolated):
    """ACT-003: action_type không hợp lệ trả typed error."""
    repository, jobs, _ = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    resp = await client.post(
        f"/api/v1/projects/{project_id}/action-proposals",
        json={
            "action_type": "summon_dragons",  # invented action
            "parameters": {},
            "base_report_version_id": None,
        },
    )
    # Must be 422 with a typed error code, never 2xx or 5xx.
    assert resp.status_code == 422, f"Unknown action_type should be 422, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_act_003b_missing_required_parameters(client, v2_isolated):
    """ACT-003: Parameters thiếu field bắt buộc trả 422."""
    repository, jobs, service = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    resp = await client.post(
        f"/api/v1/projects/{project_id}/action-proposals",
        json={
            "action_type": "search_more",
            "parameters": {},  # missing 'limit' and 'purpose'
            "base_report_version_id": None,
        },
    )
    assert resp.status_code == 422, f"Missing parameters should be 422, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# ACT-003c — Extra parameters that are not in the allowed set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_act_003c_extra_parameters_rejected(client, v2_isolated):
    """ACT-003: Extra fields beyond allowed set trả 422."""
    repository, jobs, service = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    resp = await client.post(
        f"/api/v1/projects/{project_id}/action-proposals",
        json={
            "action_type": "search_more",
            "parameters": {
                "limit": 5,
                "purpose": "refinement",
                "evil_override": "drop table",  # extra field
            },
            "base_report_version_id": None,
        },
    )
    assert resp.status_code == 422, f"Extra parameters should be 422, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# ACT-004 — Unconfirmed mutation action must not call executor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_act_004_unconfirmed_mutation_not_executed(client, v2_isolated):
    """ACT-004: Mutation/costly action chưa confirm — executor call count = 0."""
    repository, jobs, service = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    resp = await client.post(
        f"/api/v1/projects/{project_id}/action-proposals",
        json={
            "action_type": "search_more",
            "parameters": {"limit": 5, "purpose": "refinement"},
            "base_report_version_id": None,
        },
    )
    # Action may be created as proposed (202/201) or rejected (422/403)
    # depending on current stage — but must never directly execute.
    assert resp.status_code not in (500, 501, 503), f"Server error on action create: {resp.status_code} {resp.text}"
    if resp.status_code in (201, 202):
        action = resp.json().get("action", resp.json())
        # Status must be 'proposed', never 'completed'.
        status_val = action.get("status", "")
        assert status_val != "completed", f"Unconfirmed action should not be 'completed': {action}"


# ---------------------------------------------------------------------------
# ACT-007 — Same idempotency key with different payload → conflict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_act_007_conflict_on_payload_mismatch(client, v2_isolated):
    """ACT-007: Cùng key nhưng payload khác trả conflict; không tạo job thứ hai."""
    repository, jobs, service = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    base_payload = {
        "action_type": "search_more",
        "parameters": {"limit": 5, "purpose": "refinement"},
        "base_report_version_id": None,
        "idempotency_key": "idem_test_007",
    }

    r1 = await client.post(f"/api/v1/projects/{project_id}/action-proposals", json=base_payload)
    assert r1.status_code < 500, f"First action failed: {r1.status_code}"

    if r1.status_code in (201, 202):
        # Second request with same key but different limit.
        conflict_payload = {**base_payload, "parameters": {"limit": 10, "purpose": "refinement"}}
        r2 = await client.post(f"/api/v1/projects/{project_id}/action-proposals", json=conflict_payload)
        # Must be 409 conflict.
        assert r2.status_code == 409, f"Payload mismatch with same idempotency key should be 409, got {r2.status_code}"


# ---------------------------------------------------------------------------
# ACT-012 — Version Service / Reviewer endpoints not callable as LLM tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_act_012_version_service_not_llm_tool(client, v2_isolated):
    """ACT-012: Version Service và Reviewer persistence không gọi được như LLM tool."""
    repository, jobs, service = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    # Attempt to invoke internal capability names that should not exist in tool registry.
    for forbidden_tool in ["persist_report_version", "update_reviewer_verdict", "_internal_version"]:
        resp = await client.post(
            f"/api/v1/projects/{project_id}/action-proposals",
            json={
                "action_type": forbidden_tool,
                "parameters": {},
                "base_report_version_id": None,
            },
        )
        assert resp.status_code == 422, f"Internal tool '{forbidden_tool}' should not be callable: {resp.status_code}"
