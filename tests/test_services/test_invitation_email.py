import json
from types import SimpleNamespace

import httpx
import pytest

from src.services import invitation_email as email_module
from src.services.invitation_email import InvitationEmailService


def settings(**overrides):
    values = {
        "resend_api_key": "re_test",
        "resend_from_email": "Research Review <review@updates.example.com>",
        "resend_reply_to": "team@example.com",
        "resend_timeout_seconds": 10.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def invitation():
    return {
        "invitation_id": "inv_123",
        "email": "reviewer@example.com",
        "email_attempts": 0,
        "project_name": "Grounded AI",
        "inviter_name": "Alice",
        "expires_at": "2026-08-11T00:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_resend_email_contains_invitation_and_idempotency_key(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "email_123"})

    monkeypatch.setattr(email_module, "get_settings", lambda: settings())
    service = InvitationEmailService(httpx.MockTransport(handler))
    result = await service.send_review_invitation(invitation(), "https://app.example.com/?invitation=secret")

    assert result.status == "sent"
    assert result.provider_id == "email_123"
    assert captured["body"]["to"] == ["reviewer@example.com"]
    assert "https://app.example.com/?invitation=secret" in captured["body"]["text"]
    assert captured["headers"]["idempotency-key"] == "review-invitation-inv_123-1"
    assert captured["headers"]["authorization"] == "Bearer re_test"


@pytest.mark.asyncio
async def test_invitation_email_is_optional(monkeypatch):
    monkeypatch.setattr(
        email_module,
        "get_settings",
        lambda: settings(resend_api_key="", resend_from_email=""),
    )
    result = await InvitationEmailService().send_review_invitation(
        invitation(), "https://app.example.com/?invitation=secret"
    )
    assert result.status == "not_configured"


@pytest.mark.asyncio
async def test_resend_failure_is_returned_without_raising(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "Domain is not verified"})

    monkeypatch.setattr(email_module, "get_settings", lambda: settings())
    result = await InvitationEmailService(httpx.MockTransport(handler)).send_review_invitation(
        invitation(), "https://app.example.com/?invitation=secret"
    )
    assert result.status == "failed"
    assert result.error == "Resend returned HTTP 422: Domain is not verified"
