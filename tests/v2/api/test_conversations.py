"""CHAT-001..010 — CapabilitySnapshot, conversation, citation, SSE.

Test contract §5.B  (Grounded conversation và citation)
File: tests/v2/api/test_conversations.py
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.v2.conftest import ACTOR_ALICE, ACTOR_OUTSIDER

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _login(client: AsyncClient, actor_id: str = ACTOR_ALICE, role: str = "researcher"):
    resp = await client.post("/api/v1/auth/session", json={"bootstrap_token": f"{role}:{actor_id}"})
    assert resp.status_code in (200, 201), resp.text


async def _create_project(client: AsyncClient) -> dict:
    resp = await client.post("/api/v1/projects", json={"name": "Chat Test Project", "description": ""})
    assert resp.status_code == 201, resp.text
    return resp.json()["project"]


# ---------------------------------------------------------------------------
# CHAT-001 — CapabilitySnapshot returned at capability endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_001_capability_snapshot_returned(client, v2_isolated):
    """CHAT-001: Backend tạo CapabilitySnapshot và trả về đúng cấu trúc."""
    repository, jobs, _ = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    resp = await client.get(f"/api/v1/projects/{project_id}/capabilities")
    assert resp.status_code == 200, resp.text
    snap = resp.json()["capability_snapshot"]
    assert snap["project_id"] == project_id
    assert snap["data_stage"] in {"empty", "abstract_ready", "search_running"}
    assert "allowed_tools" in snap
    assert "snapshot_schema_version" in snap
    assert snap["snapshot_schema_version"] == "2.0"


@pytest.mark.asyncio
async def test_chat_001b_capability_snapshot_has_actor_and_role(client, v2_isolated):
    """CHAT-001: Snapshot lưu actor_id và project_role."""
    repository, jobs, _ = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    resp = await client.get(f"/api/v1/projects/{project_id}/capabilities")
    assert resp.status_code == 200
    snap = resp.json()["capability_snapshot"]
    assert snap["actor_id"] == ACTOR_ALICE
    assert snap["project_role"] in {"owner", "researcher", "reviewer"}


# ---------------------------------------------------------------------------
# CHAT-002 — Stage 'empty' limits allowed operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_002_empty_stage_data_stage(client, v2_isolated):
    """CHAT-002: Stage empty khi chưa có report."""
    repository, jobs, _ = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    resp = await client.get(f"/api/v1/projects/{project_id}/capabilities")
    assert resp.status_code == 200
    snap = resp.json()["capability_snapshot"]
    # Fresh project must be 'empty' or 'search_running' (no report yet).
    assert snap["data_stage"] in {"empty", "search_running"}
    assert snap["factual_answers_allowed"] is False or snap["data_stage"] == "abstract_ready"


# ---------------------------------------------------------------------------
# CHAT-003 / CHAT-004 — Conversation creation and citation validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_003_conversation_creation(client, v2_isolated):
    """CHAT-003: POST /conversations creates conversation with correct project binding."""
    repository, jobs, service = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    resp = await client.post(
        f"/api/v1/projects/{project_id}/conversations",
        json={"initial_report_version_id": None},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # POST /conversations returns {"conversation": {...}}
    conv = body.get("conversation", body)
    assert "conversation_id" in conv, f"conversation_id missing from response: {body}"
    assert conv.get("project_id") == project_id, f"Wrong project_id in conversation: {conv}"


@pytest.mark.asyncio
async def test_chat_003b_outsider_cannot_create_conversation(client, v2_isolated):
    """CHAT-003: Outsider bị từ chối tạo conversation."""
    repository, jobs, _ = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]
    await client.delete("/api/v1/auth/session")

    # Login as outsider.
    await _login(client, ACTOR_OUTSIDER)
    resp = await client.post(
        f"/api/v1/projects/{project_id}/conversations",
        json={"initial_report_version_id": None},
    )
    assert resp.status_code in (403, 404), f"Outsider should not create conversation: {resp.status_code}"


# ---------------------------------------------------------------------------
# CHAT-007 — Idempotency: same client_message_id does not duplicate turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_007_idempotent_message(client, v2_isolated):
    """CHAT-007: Retry cùng client_message_id không tạo turn trùng."""
    repository, jobs, _ = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    conv_resp = await client.post(
        f"/api/v1/projects/{project_id}/conversations",
        json={"initial_report_version_id": None},
    )
    assert conv_resp.status_code == 201
    conv_id = conv_resp.json()["conversation"]["conversation_id"]

    # Send a message — we don't assert the response body here since the
    # LLM is not mocked.  We verify HTTP layer doesn't crash on duplicate.
    msg_payload = {
        "content": "What is the main finding?",
        "client_message_id": "cmsg_test_idempotency_001",
    }

    # Two identical calls.
    r1 = await client.post(f"/api/v1/conversations/{conv_id}/messages", json=msg_payload)
    r2 = await client.post(f"/api/v1/conversations/{conv_id}/messages", json=msg_payload)

    # Either the second is idempotent (same 2xx) or returns an explicit
    # conflict/idempotency code — never a server error.
    assert r1.status_code < 500, f"First message failed: {r1.status_code} {r1.text}"
    assert r2.status_code < 500, f"Duplicate message caused server error: {r2.status_code}"
    # The two successful responses should reference the same turn.
    if r1.status_code < 300 and r2.status_code < 300:
        assert r1.json().get("message_id") == r2.json().get("message_id"), (
            "Duplicate client_message_id produced two distinct message_ids"
        )


# ---------------------------------------------------------------------------
# CHAT-008 — Stale report version triggers CONVERSATION_CONTEXT_STALE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_008_stale_report_version(client, v2_isolated):
    """CHAT-008: expected_report_version_id cũ trả CONVERSATION_CONTEXT_STALE."""
    repository, jobs, service = v2_isolated
    await _login(client)
    project = await _create_project(client)
    project_id = project["project_id"]

    conv_resp = await client.post(
        f"/api/v1/projects/{project_id}/conversations",
        json={"initial_report_version_id": None},
    )
    assert conv_resp.status_code == 201
    conv_id = conv_resp.json()["conversation"]["conversation_id"]

    # Send message with a deliberately wrong/old version id.
    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={
            "content": "Summarise",
            "client_message_id": "cmsg_stale_001",
            "expected_report_version_id": "rpt_version_does_not_exist",
        },
    )
    # Must be rejected with 409 and code CONVERSATION_CONTEXT_STALE,
    # or 404 if the version is not found — but never 5xx.
    assert resp.status_code in (404, 409, 422), f"Stale version should be rejected, got {resp.status_code}: {resp.text}"
    if resp.status_code == 409:
        assert resp.json().get("detail", {}).get("code") == "CONVERSATION_CONTEXT_STALE", (
            f"Expected CONVERSATION_CONTEXT_STALE code: {resp.json()}"
        )
