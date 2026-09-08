"""Fail-closed main-backend adapter for optional Sandbox Control requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from sandbox_service.domain.sessions import CreateSandboxSessionRequest, ResearchContextSnapshot, SandboxSessionResponse
from sandbox_service.integration.auth import SignedServiceAuth
from sandbox_service.integration.context_mapping import ContextMappingError, ResearchContextMapper


class SandboxServiceUnavailable(RuntimeError):
    pass


class SandboxGatewayRejected(ValueError):
    pass


@dataclass(frozen=True)
class SandboxGatewaySettings:
    enabled: bool = False
    hypothesis_enabled: bool = False
    graph_overlay_enabled: bool = False
    data_analysis_enabled: bool = False

    def allows(self, mode: str) -> bool:
        return self.enabled and {
            "hypothesis": self.hypothesis_enabled,
            "graph_overlay": self.graph_overlay_enabled,
            "data_analysis": self.data_analysis_enabled,
        }.get(mode, False)


@dataclass(frozen=True)
class SandboxGatewayOutcome:
    status: Literal["created", "disabled", "unavailable"]
    session: SandboxSessionResponse | None = None
    reason: str | None = None

    @property
    def show_sandbox_action(self) -> bool:
        return self.status == "created" or self.status == "unavailable"


class SandboxControlClient(Protocol):
    async def create_session(
        self,
        *,
        project_id: str,
        actor_id: str,
        correlation_id: str,
        request: CreateSandboxSessionRequest,
        context_snapshot: ResearchContextSnapshot | None,
    ) -> SandboxSessionResponse: ...


class HttpSandboxControlClient:
    """Small client library; only explicit gateway calls open an outbound connection."""

    _PATH = "/internal/v1/gateway/sessions"

    def __init__(
        self,
        *,
        base_url: str,
        service_auth: SignedServiceAuth,
        timeout_seconds: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = service_auth
        self._timeout = timeout_seconds
        self._transport = transport

    async def create_session(
        self,
        *,
        project_id: str,
        actor_id: str,
        correlation_id: str,
        request: CreateSandboxSessionRequest,
        context_snapshot: ResearchContextSnapshot | None,
    ) -> SandboxSessionResponse:
        body = {
            "request": request.model_dump(mode="json"),
            "context_snapshot": context_snapshot.model_dump(mode="json") if context_snapshot else None,
        }
        headers = self._auth.sign(
            method="POST", path=self._PATH, body=body,
            project_id=project_id, actor_id=actor_id, correlation_id=correlation_id,
        )
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(f"{self._base_url}{self._PATH}", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise SandboxServiceUnavailable("Sandbox Control Service is unavailable") from exc
        if response.status_code >= 500:
            raise SandboxServiceUnavailable("Sandbox Control Service is unavailable")
        if response.status_code >= 400:
            raise SandboxGatewayRejected(f"Sandbox Control rejected the request ({response.status_code})")
        return SandboxSessionResponse.model_validate(response.json())


class SandboxGateway:
    """The only backend-facing entrypoint.  Disabled/down sandbox never raises to core flows."""

    def __init__(
        self,
        *,
        settings: SandboxGatewaySettings,
        client: SandboxControlClient,
        context_mapper: ResearchContextMapper,
    ) -> None:
        self._settings = settings
        self._client = client
        self._mapper = context_mapper

    async def open_session(
        self,
        *,
        project_id: str,
        actor_id: str,
        correlation_id: str,
        request: CreateSandboxSessionRequest,
        context_snapshot: ResearchContextSnapshot | None = None,
    ) -> SandboxGatewayOutcome:
        if not self._settings.allows(request.mode.value):
            return SandboxGatewayOutcome(status="disabled", reason="sandbox capability is disabled")
        if request.entrypoint.value == "manual":
            if context_snapshot is not None:
                raise SandboxGatewayRejected("manual sessions cannot carry a research context")
        else:
            if context_snapshot is None:
                raise SandboxGatewayRejected("a mapped signed context is required")
            try:
                self._mapper.verify(
                    context_snapshot,
                    project_id=project_id,
                    entrypoint=request.entrypoint,
                    source_resource_id=request.source_resource_id or "",
                )
            except ContextMappingError as exc:
                raise SandboxGatewayRejected(str(exc)) from exc
        try:
            session = await self._client.create_session(
                project_id=project_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                request=request,
                context_snapshot=context_snapshot,
            )
        except SandboxServiceUnavailable:
            return SandboxGatewayOutcome(status="unavailable", reason="sandbox service is unavailable")
        return SandboxGatewayOutcome(status="created", session=session)
