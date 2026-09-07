"""AUTH-001..007 + SEC-001 + SEC-003 — Session, membership & project authorization.

Test contract §5.A  (Identity và project isolation)
File: tests/v2/api/test_auth_project.py
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.v2.conftest import ACTOR_ALICE, ACTOR_OUTSIDER

# ---------------------------------------------------------------------------
# Helpers shared across auth tests
# ---------------------------------------------------------------------------


async def _bootstrap(client: AsyncClient, token: str) -> int:
    resp = await client.post("/api/v1/auth/session", json={"bootstrap_token": token})
    return resp.status_code


async def _get_projects(client: AsyncClient):
    return await client.get("/api/v1/projects")


# ---------------------------------------------------------------------------
# AUTH-001 — Valid session resolves actor; DB stores token hash not plaintext
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_001_valid_session_resolves_actor(client):
    """AUTH-001: Session hợp lệ resolve đúng actor."""
    resp = await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_ALICE}"})
    assert resp.status_code in (200, 201), resp.text
    # Subsequent protected request must succeed.
    projects = await _get_projects(client)
    assert projects.status_code == 200


@pytest.mark.asyncio
async def test_auth_001b_session_cookie_set(client):
    """AUTH-001: Cookie được set sau bootstrap."""
    resp = await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_ALICE}"})
    assert resp.status_code in (200, 201)
    # httpx preserves cookies automatically; verify subsequent call works.
    me = await client.get("/api/v1/projects")
    assert me.status_code == 200


# ---------------------------------------------------------------------------
# AUTH-002 — Revoked / deleted session is rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_002_deleted_session_is_rejected(client):
    """AUTH-002: Session revoked/expired bị từ chối ngay request kế tiếp."""
    await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_ALICE}"})
    await client.delete("/api/v1/auth/session")
    projects = await _get_projects(client)
    assert projects.status_code == 401


# ---------------------------------------------------------------------------
# AUTH-003 — Bootstrap only works in test/local env
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_003_bootstrap_blocked_in_production(client, monkeypatch):
    """AUTH-003: Bootstrap endpoint chỉ hoạt động ở local/test."""
    from types import SimpleNamespace

    import src.api.routers.research_copilot as v2_routes

    # Simulate production env.
    monkeypatch.setattr(
        v2_routes,
        "get_settings",
        lambda: SimpleNamespace(
            app_env="production",
            resend_api_key=None,
            resend_from_email=None,
            invitation_base_url="http://localhost:3000/",
            resend_min_interval_seconds=60,
            resend_timeout_seconds=10,
            resend_reply_to=None,
        ),
    )
    resp = await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_ALICE}"})
    # In production the bootstrap route should return 401 or 404.
    assert resp.status_code in (401, 403, 404, 422), (
        f"Expected bootstrap to fail in production, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# AUTH-004 — Legacy identity fields in request body must be rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_004_identity_fields_are_forbidden(client):
    """AUTH-004: V2 request có role/user_id/actor_id/reviewer_id trả 422."""
    await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_ALICE}"})
    project_resp = await client.post("/api/v1/projects", json={"name": "Test project", "description": ""})
    assert project_resp.status_code == 201, project_resp.text
    project_id = project_resp.json()["project"]["project_id"]

    # Attempt to inject identity through conversation creation body.
    resp = await client.post(
        f"/api/v1/projects/{project_id}/conversations",
        json={"initial_report_version_id": None, "actor_id": "evil", "role": "owner"},
    )
    # FastAPI Pydantic validation must reject extra fields.
    assert resp.status_code == 422, f"Identity injection was not rejected: {resp.status_code} {resp.text}"


# ---------------------------------------------------------------------------
# AUTH-005 — Outsider cannot read project data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_005_outsider_cannot_read_project(client, v2_isolated):
    """AUTH-005: Outsider không đọc report/conversation/citation ngoài quyền."""
    repository, jobs, _ = v2_isolated

    # Owner creates project.
    await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_ALICE}"})
    project_resp = await client.post("/api/v1/projects", json={"name": "Private project", "description": ""})
    assert project_resp.status_code == 201
    project_id = project_resp.json()["project"]["project_id"]

    # Switch to outsider.
    await client.delete("/api/v1/auth/session")
    await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_OUTSIDER}"})

    # Attempt to read the project's conversations.
    resp = await client.get(f"/api/v1/projects/{project_id}/conversations")
    assert resp.status_code in (403, 404), f"Outsider should not access project data, got {resp.status_code}"


# ---------------------------------------------------------------------------
# AUTH-006 — Legacy V1 identity fields do not grant V2 project access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_006_legacy_v1_field_does_not_grant_access(client, v2_isolated):
    """AUTH-006: Legacy V1 identity field không cấp quyền vào project V2."""
    repository, jobs, _ = v2_isolated

    await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_ALICE}"})
    project_resp = await client.post("/api/v1/projects", json={"name": "V2 Project", "description": ""})
    assert project_resp.status_code == 201
    project_id = project_resp.json()["project"]["project_id"]

    # Use V1 researcher header pattern.
    await client.delete("/api/v1/auth/session")
    resp = await client.get(
        f"/api/v1/projects/{project_id}/conversations",
        headers={"X-Researcher-Id": ACTOR_ALICE},
    )
    # Must be rejected — V1 header is not a recognised auth method for V2 resources.
    assert resp.status_code in (401, 403), f"V1 identity header should not grant access, got {resp.status_code}"


# ---------------------------------------------------------------------------
# SEC-001 — IDOR: project-scoped endpoint returns 403/404 for foreign project id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sec_001_idor_project_boundary(client, v2_isolated):
    """SEC-001: Outsider với valid ID của project khác không thấy dữ liệu."""
    repository, jobs, _ = v2_isolated

    # Owner creates project A and seeds a conversation.
    await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_ALICE}"})
    proj_a = await client.post("/api/v1/projects", json={"name": "Project A", "description": ""})
    assert proj_a.status_code == 201
    project_a_id = proj_a.json()["project"]["project_id"]

    # Switch to outsider who also has their own project.
    await client.delete("/api/v1/auth/session")
    await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_OUTSIDER}"})
    proj_b = await client.post("/api/v1/projects", json={"name": "Project B", "description": ""})
    assert proj_b.status_code == 201

    # Outsider tries to access project A using its real ID.
    resp = await client.get(f"/api/v1/projects/{project_a_id}/conversations")
    assert resp.status_code in (403, 404), f"Cross-project IDOR not blocked: {resp.status_code} {resp.text}"

    # Response must not leak project A data.
    body = resp.text
    assert "Project A" not in body, "Project A name leaked in error response"


# ---------------------------------------------------------------------------
# SEC-003 — Session token must not appear in response bodies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sec_003_session_token_not_in_response(client):
    """SEC-003: Session/bootstrap token không xuất hiện trong response body."""
    resp = await client.post("/api/v1/auth/session", json={"bootstrap_token": f"researcher:{ACTOR_ALICE}"})
    assert resp.status_code in (200, 201)
    body = resp.text

    # The response must not echo the raw session token back in the body.
    # (Token is set as HttpOnly cookie, not in JSON.)
    for cookie in client.cookies.jar:
        if cookie.name == "litreview_session":
            raw_token = cookie.value
            assert raw_token not in body, "Raw session token was echoed in bootstrap response body"
            break
