"""Feature and identity boundaries shared by every browser-facing Sandbox API."""

from __future__ import annotations

from inspect import isawaitable
from typing import Annotated, Protocol
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from sandbox_service.config import SandboxSettings
from sandbox_service.domain.sessions import SandboxMode
from sandbox_service.integration.auth import ServiceAuthError, SignedServiceAuth


class TrustedActorContext(BaseModel):
    """Identity already authenticated by the core backend or trusted edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str = Field(min_length=1, max_length=255)
    project_id: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)


class TrustedActorContextResolver(Protocol):
    def resolve(self, *, request: Request, project_id: str) -> TrustedActorContext: ...


class SignedServiceActorContextResolver:
    """Authenticate exact BFF request bytes and derive immutable actor context."""

    def __init__(self, service_auth: SignedServiceAuth) -> None:
        self._service_auth = service_auth

    async def resolve(self, *, request: Request, project_id: str) -> TrustedActorContext:
        body = await request.body()
        try:
            signed_project_id, actor_id, correlation_id = self._service_auth.verify_bytes(
                method=request.method,
                path=request.url.path,
                body=body,
                headers=request.headers,
            )
        except ServiceAuthError as exc:
            raise HTTPException(
                status_code=401,
                detail={
                    "error_code": "SERVICE_AUTH_INVALID",
                    "message": str(exc),
                    "retryable": False,
                    "details": {},
                },
            ) from exc
        return TrustedActorContext(
            actor_id=actor_id,
            project_id=signed_project_id,
            correlation_id=correlation_id,
        )


def get_sandbox_settings(request: Request) -> SandboxSettings:
    return getattr(request.app.state, "sandbox_settings", None) or SandboxSettings()


def _feature_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "error_code": "SANDBOX_FEATURE_DISABLED",
            "message": message,
            "retryable": False,
            "details": {},
        },
    )


def require_sandbox_enabled(request: Request) -> None:
    if not get_sandbox_settings(request).enabled:
        raise _feature_error("Sandbox is not enabled")


def require_hypothesis_enabled(request: Request) -> None:
    settings = get_sandbox_settings(request)
    if not settings.allows_mode(SandboxMode.HYPOTHESIS.value):
        raise _feature_error("Hypothesis mode is not enabled")


def require_graph_overlay_enabled(request: Request) -> None:
    settings = get_sandbox_settings(request)
    if not settings.allows_mode(SandboxMode.GRAPH_OVERLAY.value):
        raise _feature_error("Graph overlay mode is not enabled")


def require_data_analysis_enabled(request: Request) -> None:
    settings = get_sandbox_settings(request)
    if not settings.allows_mode(SandboxMode.DATA_ANALYSIS.value):
        raise _feature_error("Data analysis mode is not enabled")


def require_ai_enabled(request: Request) -> None:
    require_sandbox_enabled(request)
    if not get_sandbox_settings(request).ai_enabled:
        raise _feature_error("Sandbox AI capability is not enabled")


def require_result_interpretation_enabled(request: Request) -> None:
    require_data_analysis_enabled(request)
    settings = get_sandbox_settings(request)
    if not settings.ai_enabled or not settings.result_interpretation_enabled:
        raise _feature_error("Result interpretation capability is not enabled")


def ensure_mode_enabled(request: Request, mode: SandboxMode | str) -> None:
    value = mode.value if isinstance(mode, SandboxMode) else mode
    if not get_sandbox_settings(request).allows_mode(value):
        raise _feature_error(f"Sandbox mode '{value}' is not enabled")


async def get_actor_context(
    request: Request,
    project_id: str,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-Id")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> TrustedActorContext:
    """Resolve an authenticated actor; arbitrary browser headers are disabled by default."""

    cached = getattr(request.state, "sandbox_actor_context", None)
    if cached is not None:
        context = TrustedActorContext.model_validate(cached)
    else:
        resolver = getattr(request.app.state, "sandbox_actor_context_resolver", None)
        if resolver is not None:
            resolved = resolver.resolve(request=request, project_id=project_id)
            context = await resolved if isawaitable(resolved) else resolved
            context = TrustedActorContext.model_validate(context)
        elif getattr(get_sandbox_settings(request), "allow_local_actor_headers", False):
            if not x_actor_id:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "error_code": "SANDBOX_AUTHENTICATION_REQUIRED",
                        "message": "X-Actor-Id is required in explicitly enabled local-header mode",
                        "retryable": False,
                        "details": {},
                    },
                )
            context = TrustedActorContext(
                actor_id=x_actor_id,
                project_id=project_id,
                correlation_id=x_correlation_id or str(uuid4()),
            )
        else:
            raise HTTPException(
                status_code=401,
                detail={
                    "error_code": "SANDBOX_AUTHENTICATION_REQUIRED",
                    "message": "A trusted actor context is required",
                    "retryable": False,
                    "details": {},
                },
            )
    if context.project_id != project_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PROJECT_ACCESS_DENIED",
                "message": "Actor context does not grant access to this project",
                "retryable": False,
                "details": {},
            },
        )
    request.state.sandbox_actor_context = context
    return context


async def get_actor_id(
    context: Annotated[TrustedActorContext, Depends(get_actor_context)],
) -> str:
    return context.actor_id
