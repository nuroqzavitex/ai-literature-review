from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

import httpx

from src.config import get_settings


@dataclass(frozen=True)
class EmailDeliveryResult:
    status: str
    provider_id: str | None = None
    error: str | None = None


class InvitationEmailService:
    """Send transactional reviewer invitations without owning invitation state."""

    endpoint = "https://api.resend.com/emails"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def send_review_invitation(self, invitation: dict[str, Any], invitation_url: str) -> EmailDeliveryResult:
        settings = get_settings()
        app_env = getattr(settings, "app_env", "production")
        if app_env != "production" or not settings.resend_api_key or not settings.resend_from_email:
            return EmailDeliveryResult(status="not_configured")

        project_name = str(invitation.get("project_name") or "dự án nghiên cứu")
        inviter_name = str(invitation.get("inviter_name") or "Một researcher")
        expires_at = str(invitation.get("expires_at") or "")
        safe_project = escape(project_name)
        safe_inviter = escape(inviter_name)
        safe_url = escape(invitation_url, quote=True)
        safe_expiry = escape(expires_at)
        payload: dict[str, Any] = {
            "from": settings.resend_from_email,
            "to": [invitation["email"]],
            "subject": f"Lời mời review dự án: {project_name}",
            "html": (
                '<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;color:#1d2721">'
                "<h2>Bạn được mời làm reviewer</h2>"
                f"<p><strong>{safe_inviter}</strong> đã mời bạn review một báo cáo trong dự án "
                f"<strong>{safe_project}</strong>.</p>"
                "<p>Đăng nhập để xem nội dung được phân công và phản hồi lời mời.</p>"
                f'<p><a href="{safe_url}" style="display:inline-block;padding:12px 18px;'
                'background:#254f3b;color:white;text-decoration:none;border-radius:8px">'
                "Xem lời mời</a></p>"
                f'<p style="color:#657069;font-size:13px">Lời mời hết hạn: {safe_expiry}</p>'
                '<p style="color:#657069;font-size:13px">Nếu bạn không mong đợi email này, '
                "hãy bỏ qua và không chia sẻ liên kết.</p></div>"
            ),
            "text": (
                f"{inviter_name} đã mời bạn review một báo cáo trong dự án {project_name}.\n\n"
                f"Mở lời mời: {invitation_url}\n\nLời mời hết hạn: {expires_at}"
            ),
        }
        if settings.resend_reply_to:
            payload["reply_to"] = settings.resend_reply_to

        attempt = int(invitation.get("email_attempts") or 0) + 1
        headers = {
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Idempotency-Key": f"review-invitation-{invitation['invitation_id']}-{attempt}",
        }
        try:
            async with httpx.AsyncClient(timeout=settings.resend_timeout_seconds, transport=self.transport) as client:
                response = await client.post(self.endpoint, headers=headers, json=payload)
            if response.is_error:
                detail = self._response_error(response)
                return EmailDeliveryResult(status="failed", error=detail)
            data = response.json()
            provider_id = data.get("id") if isinstance(data, dict) else None
            if not provider_id:
                return EmailDeliveryResult(status="failed", error="Resend response did not include an email id")
            return EmailDeliveryResult(status="sent", provider_id=str(provider_id))
        except (httpx.HTTPError, ValueError) as exc:
            return EmailDeliveryResult(status="failed", error=f"Resend request failed: {exc}")

    @staticmethod
    def _response_error(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict):
                message = body.get("message") or body.get("name")
                if message:
                    return f"Resend returned HTTP {response.status_code}: {message}"
        except ValueError:
            pass
        return f"Resend returned HTTP {response.status_code}"
