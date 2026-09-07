"""Internal signed service endpoint; never accepts browser actor/context payloads."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from sandbox_service.api.dependencies import ensure_mode_enabled
from sandbox_service.domain.sessions import CreateSandboxSessionRequest, ResearchContextSnapshot, SandboxEntrypoint, SandboxSessionResponse
from sandbox_service.integration.auth import ServiceAuthError, SignedServiceAuth
from sandbox_service.integration.context_mapping import ContextMappingError, ResearchContextMapper
from sandbox_service.session_service import SandboxSessionService


class GatewayCreateSessionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: CreateSandboxSessionRequest
    context_snapshot: ResearchContextSnapshot | None = None


class _SignedSnapshotProvider:
    def __init__(self, *, snapshot: ResearchContextSnapshot, mapper: ResearchContextMapper) -> None:
        self._snapshot = snapshot
        self._mapper = mapper

    async def resolve_snapshot(
        self, *, project_id: str, entrypoint: SandboxEntrypoint, source_resource_id: str,
        actor_id: str, correlation_id: str,
    ) -> ResearchContextSnapshot:
        return self._mapper.verify(
            self._snapshot,
            project_id=project_id,
            entrypoint=entrypoint,
            source_resource_id=source_resource_id,
        )


def create_gateway_router(*, service_auth: SignedServiceAuth, context_mapper: ResearchContextMapper) -> APIRouter:
    router = APIRouter(tags=["sandbox-internal-gateway"])

    @router.post("/internal/v1/gateway/sessions", response_model=SandboxSessionResponse, status_code=status.HTTP_201_CREATED)
    async def create_gateway_session(payload: GatewayCreateSessionPayload, request: Request) -> SandboxSessionResponse:
        body = payload.model_dump(mode="json")
        try:
            project_id, actor_id, correlation_id = service_auth.verify(
                method="POST", path="/internal/v1/gateway/sessions", body=body, headers=request.headers,
            )
        except ServiceAuthError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error_code": "SERVICE_AUTH_INVALID", "message": str(exc)}) from exc
        ensure_mode_enabled(request, payload.request.mode)
        if payload.request.entrypoint is SandboxEntrypoint.MANUAL:
            if payload.context_snapshot is not None:
                raise HTTPException(status_code=422, detail={"error_code": "CONTEXT_INVALID"})
            service = SandboxSessionService(repository=request.app.state.sandbox_repository)
        else:
            if payload.context_snapshot is None:
                raise HTTPException(status_code=422, detail={"error_code": "CONTEXT_REQUIRED"})
            service = SandboxSessionService(
                repository=request.app.state.sandbox_repository,
                context_provider=_SignedSnapshotProvider(snapshot=payload.context_snapshot, mapper=context_mapper),
            )
        try:
            return await service.create_session(
                project_id=project_id,
                request=payload.request,
                actor_id=actor_id,
                correlation_id=correlation_id,
            )
        except ContextMappingError as exc:
            raise HTTPException(status_code=409, detail={"error_code": "RESEARCH_CONTEXT_STALE", "message": str(exc)}) from exc

    return router
