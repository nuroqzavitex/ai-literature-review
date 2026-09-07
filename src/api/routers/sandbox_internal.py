"""HMAC-authenticated Core API consumed only by Sandbox Control Service."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.agents.research_sandbox.application.core_integration import (
    CoreSandboxIntegrationError,
    CoreSandboxIntegrationService,
)
from src.agents.research_sandbox.infrastructure.gateway import (
    SandboxConfigurationError,
    SignedSandboxRequestAuth,
)
from src.api.routers import research_copilot as core_routes
from src.config import Settings, get_settings

router = APIRouter(prefix="/internal/v1/sandbox", tags=["Sandbox internal"])


@dataclass(frozen=True)
class SignedSandboxActor:
    project_id: str
    actor_id: str
    correlation_id: str


class AdoptionPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sandbox_proposal_id: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=64)
    base_graph_version_id: str | None = Field(default=None, max_length=255)


class AdoptionDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sandbox_proposal_id: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    rationale: str = Field(min_length=1, max_length=10_000)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_bundle: dict[str, Any]


@lru_cache(maxsize=8)
def _authenticator(key: str, key_id: str) -> SignedSandboxRequestAuth:
    return SignedSandboxRequestAuth(key=key, key_id=key_id)


async def require_signed_sandbox_actor(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SignedSandboxActor:
    if not settings.sandbox_enabled or len(settings.sandbox_service_auth_key.encode("utf-8")) < 32:
        raise HTTPException(status_code=503, detail={"code": "SANDBOX_DISABLED"})
    try:
        project_id, actor_id, correlation_id = _authenticator(
            settings.sandbox_service_auth_key,
            settings.sandbox_service_auth_key_id,
        ).verify_bytes(
            method=request.method,
            path=request.url.path,
            body=await request.body(),
            headers=request.headers,
        )
    except SandboxConfigurationError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_SERVICE_AUTH", "message": str(exc)},
        ) from exc
    if project_id != request.path_params.get("project_id"):
        raise HTTPException(status_code=403, detail={"code": "PROJECT_SCOPE_MISMATCH"})
    return SignedSandboxActor(
        project_id=project_id,
        actor_id=actor_id,
        correlation_id=correlation_id,
    )


def _service() -> CoreSandboxIntegrationService:
    return CoreSandboxIntegrationService(core_routes.v2_repository)


def _raise_core_error(exc: CoreSandboxIntegrationError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


@router.get("/projects/{project_id}/graph-snapshots/{graph_version_id}")
async def get_graph_snapshot(
    project_id: str,
    graph_version_id: str,
    actor: Annotated[SignedSandboxActor, Depends(require_signed_sandbox_actor)],
) -> dict[str, Any]:
    try:
        return _service().graph_snapshot(
            project_id=project_id,
            graph_version_id=graph_version_id,
            actor_id=actor.actor_id,
        )
    except CoreSandboxIntegrationError as exc:
        _raise_core_error(exc)


@router.post("/projects/{project_id}/adoption-preflight")
async def adoption_preflight(
    project_id: str,
    payload: AdoptionPreflightRequest,
    actor: Annotated[SignedSandboxActor, Depends(require_signed_sandbox_actor)],
) -> dict[str, bool]:
    return {
        "current": _service().adoption_is_current(
            project_id=project_id,
            actor_id=actor.actor_id,
            base_graph_version_id=payload.base_graph_version_id,
            source_type=payload.source_type,
        )
    }


@router.post("/projects/{project_id}/adoption-drafts", status_code=201)
async def create_adoption_draft(
    project_id: str,
    payload: AdoptionDraftRequest,
    actor: Annotated[SignedSandboxActor, Depends(require_signed_sandbox_actor)],
) -> dict[str, Any]:
    try:
        action = _service().create_adoption_draft(
            project_id=project_id,
            actor_id=actor.actor_id,
            correlation_id=actor.correlation_id,
            payload=payload.model_dump(mode="json"),
        )
    except CoreSandboxIntegrationError as exc:
        _raise_core_error(exc)
    return {
        "core_draft_id": action["action_id"],
        "status": action["status"],
    }
