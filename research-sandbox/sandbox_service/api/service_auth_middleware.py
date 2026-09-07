"""ASGI service-auth boundary that runs before multipart body parsing."""

from __future__ import annotations

import re
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sandbox_service.integration.auth import ServiceAuthError, SignedServiceAuth


_PROJECT_PATH = re.compile(r"^/api/v1/projects/([^/]+)(?:/|$)")


class SignedServiceAuthMiddleware:
    """Verify exact request bytes, then place trusted claims in ASGI state.

    FastAPI may parse an upload before resolving endpoint dependencies. An ASGI
    middleware therefore owns body binding and replays the unchanged bytes to the
    downstream multipart parser.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        service_auth: SignedServiceAuth,
        max_body_bytes: int = 55 * 1024 * 1024,
    ) -> None:
        self._app = app
        self._service_auth = service_auth
        self._max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        match = _PROJECT_PATH.match(path)
        if match is None:
            await self._app(scope, receive, send)
            return

        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            chunks.append(chunk)
            total_bytes += len(chunk)
            if total_bytes > self._max_body_bytes:
                await JSONResponse(
                    status_code=413,
                    content={
                        "detail": {
                            "error_code": "SANDBOX_REQUEST_TOO_LARGE",
                            "message": "Signed request exceeds the control-service limit",
                            "retryable": False,
                            "details": {},
                        }
                    },
                )(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        headers = {
            key.decode("latin-1"): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        try:
            signed_project_id, actor_id, correlation_id = self._service_auth.verify_bytes(
                method=str(scope.get("method", "GET")),
                path=path,
                body=body,
                headers=headers,
            )
        except ServiceAuthError as exc:
            await JSONResponse(
                status_code=401,
                content={
                    "detail": {
                        "error_code": "SERVICE_AUTH_INVALID",
                        "message": str(exc),
                        "retryable": False,
                        "details": {},
                    }
                },
            )(scope, receive, send)
            return
        if signed_project_id != match.group(1):
            await JSONResponse(
                status_code=403,
                content={
                    "detail": {
                        "error_code": "PROJECT_ACCESS_DENIED",
                        "message": "Signed project does not match request path",
                        "retryable": False,
                        "details": {},
                        "correlation_id": correlation_id,
                    }
                },
            )(scope, receive, send)
            return

        state: dict[str, Any] = scope.setdefault("state", {})
        state["sandbox_actor_context"] = {
            "actor_id": actor_id,
            "project_id": signed_project_id,
            "correlation_id": correlation_id,
        }
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self._app(scope, replay_receive, send)
