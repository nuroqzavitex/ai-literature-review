"""Authenticated core BFF for explicit Research Sandbox actions.

This router is the browser trust boundary. It derives actor/project authority from
the existing core session, resolves context from core-owned records, and forwards
only allowlisted Sandbox paths. It is never called by GraphRAG background work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agents.research_sandbox.infrastructure.gateway import (
    SandboxConfigurationError,
    SandboxControlGateway,
    SandboxUnavailableError,
    SandboxUpstreamResponse,
    build_sandbox_gateway,
    new_correlation_id,
)
from src.api.routers import research_copilot as core_routes
from src.api.routers.research_copilot import current_actor
from src.config import get_settings

router = APIRouter(prefix="/projects/{project_id}/sandbox", tags=["Research Sandbox"])
Actor = Annotated[dict[str, Any], Depends(current_actor)]
_ID = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
_CORRELATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class OpenSandboxSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["hypothesis", "graph_overlay", "data_analysis"]
    entrypoint: Literal["manual", "graphrag_answer", "validated_candidate", "experiment_proposal"]
    source_resource_id: str | None = Field(default=None, min_length=1, max_length=255)
    source_parent_id: str | None = Field(default=None, min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    initial_question: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def validate_source(self) -> OpenSandboxSessionRequest:
        if self.entrypoint == "manual":
            if self.source_resource_id or self.source_parent_id:
                raise ValueError("manual Sandbox sessions cannot specify a source")
        elif not self.source_resource_id:
            raise ValueError("context entrypoints require source_resource_id")
        if self.entrypoint == "graphrag_answer" and not self.source_parent_id:
            raise ValueError("GraphRAG context requires source_parent_id")
        return self

    def sandbox_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude={"source_parent_id"})


@dataclass(frozen=True)
class ProxyRule:
    pattern: re.Pattern[str]
    methods: frozenset[str]
    mode: Literal["hypothesis", "graph_overlay", "data_analysis"] | None = None
    review_action: bool = False


def _rule(
    pattern: str,
    methods: set[str],
    mode: Literal["hypothesis", "graph_overlay", "data_analysis"] | None = None,
    *,
    review_action: bool = False,
) -> ProxyRule:
    return ProxyRule(re.compile(f"^(?:{pattern})$"), frozenset(methods), mode, review_action)


_PROXY_RULES = (
    _rule(rf"sandbox-sessions(?:/{_ID})?", {"GET"}),
    _rule(rf"sandbox-sessions/{_ID}/(?:close|discard)", {"POST"}),
    _rule(rf"sandbox-sessions/{_ID}/status-history", {"GET"}),
    _rule(rf"sandbox-sessions/{_ID}/context", {"GET"}),
    _rule(rf"sandbox-sessions/{_ID}/hypotheses", {"GET", "POST"}, "hypothesis"),
    _rule(rf"sandbox-sessions/{_ID}/hypotheses/{_ID}/review", {"POST"}, "hypothesis", review_action=True),
    _rule(rf"sandbox-sessions/{_ID}/experiments(?:/{_ID})?", {"GET", "POST"}, "hypothesis"),
    _rule(rf"sandbox-sessions/{_ID}/graph-overlays", {"GET", "POST"}, "graph_overlay"),
    _rule(rf"sandbox-sessions/{_ID}/graph-overlays/{_ID}", {"GET"}, "graph_overlay"),
    _rule(rf"sandbox-sessions/{_ID}/graph-overlays/{_ID}/(?:operations|assess)", {"POST"}, "graph_overlay"),
    _rule(rf"sandbox-sessions/{_ID}/graph-overlays/{_ID}/comparison", {"GET"}, "graph_overlay"),
    _rule(rf"sandbox-sessions/{_ID}/adoption-proposals", {"GET", "POST"}),
    _rule(rf"sandbox-adoption-proposals/{_ID}/review", {"POST"}, review_action=True),
    _rule(rf"sandbox-adoption-proposals/{_ID}/handoff", {"POST"}, review_action=True),
    _rule(r"datasets", {"GET", "POST"}, "data_analysis"),
    _rule(rf"datasets/{_ID}", {"GET", "DELETE"}, "data_analysis"),
    _rule(rf"datasets/{_ID}/profile", {"POST"}, "data_analysis"),
    _rule(rf"datasets/{_ID}/profiles", {"GET"}, "data_analysis"),
    _rule(rf"datasets/{_ID}/profiles/[1-9][0-9]*", {"GET"}, "data_analysis"),
    _rule(rf"datasets/{_ID}/analysis-questions(?:/{_ID})?", {"GET", "POST"}, "data_analysis"),
    _rule(rf"datasets/{_ID}/analysis-plans", {"GET", "POST"}, "data_analysis"),
    _rule(rf"analysis-plans/{_ID}/versions", {"GET"}, "data_analysis"),
    _rule(rf"analysis-plans/{_ID}/versions/[1-9][0-9]*", {"GET"}, "data_analysis"),
    _rule(rf"analysis-plans/{_ID}/versions/[1-9][0-9]*/decisions", {"GET"}, "data_analysis"),
    _rule(rf"analysis-plans/{_ID}/versions/[1-9][0-9]*/review", {"POST"}, "data_analysis", review_action=True),
    _rule(rf"analysis-plans/{_ID}/versions/[1-9][0-9]*/runs", {"GET", "POST"}, "data_analysis"),
    _rule(rf"sandbox-runs/{_ID}", {"GET"}, "data_analysis"),
    _rule(rf"sandbox-runs/{_ID}/code", {"GET"}, "data_analysis"),
    _rule(rf"sandbox-runs/{_ID}/cancel", {"POST"}, "data_analysis"),
    _rule(rf"sandbox-runs/{_ID}/artifacts", {"GET"}, "data_analysis"),
    _rule(rf"sandbox-runs/{_ID}/artifacts/{_ID}/content", {"GET"}, "data_analysis"),
    _rule(rf"sandbox-runs/{_ID}/status-history", {"GET"}, "data_analysis"),
    _rule(rf"sandbox-runs/{_ID}/validation", {"GET"}, "data_analysis"),
    _rule(rf"sandbox-runs/{_ID}/interpretation", {"GET", "POST"}, "data_analysis"),
    _rule(rf"sandbox-runs/{_ID}/citations", {"GET"}, "data_analysis"),
    _rule(rf"sandbox-runs/{_ID}/review", {"POST"}, "data_analysis", review_action=True),
    _rule(rf"sandbox-runs/{_ID}/reproducibility-bundle", {"GET"}, "data_analysis"),
)


def get_sandbox_gateway() -> SandboxControlGateway:
    return build_sandbox_gateway(settings=get_settings())


def _membership(project_id: str, actor: dict[str, Any], *, mutation: bool, review: bool = False) -> dict[str, Any]:
    allowed = None
    if mutation:
        allowed = {"owner", "researcher", "reviewer"} if review else {"owner", "researcher"}
    return core_routes.v2_service.require_membership(project_id, actor, allowed)


def _correlation_id(value: str | None) -> str:
    return value if value and _CORRELATION.fullmatch(value) else new_correlation_id()


def _response(upstream: SandboxUpstreamResponse) -> Response:
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=dict(upstream.headers),
    )


def _service_error(error: Exception) -> HTTPException:
    if isinstance(error, SandboxConfigurationError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error_code": "SANDBOX_DISABLED",
                "message": "Sandbox is disabled or not configured",
                "retryable": False,
                "details": {},
            },
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error_code": "SANDBOX_UNAVAILABLE",
            "message": "Sandbox Control Service is unavailable",
            "retryable": True,
            "details": {},
        },
    )


@router.get("/capabilities")
async def sandbox_capabilities(project_id: str, actor: Actor) -> dict[str, Any]:
    membership = _membership(project_id, actor, mutation=False)
    capabilities = get_sandbox_gateway().capabilities()
    return {**capabilities, "project_role": membership["project_role"]}


@router.post("/open-session", status_code=status.HTTP_201_CREATED)
async def open_sandbox_session(
    project_id: str,
    payload: OpenSandboxSessionRequest,
    actor: Actor,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> Response:
    _membership(project_id, actor, mutation=True)
    gateway = get_sandbox_gateway()
    context = _resolve_context(
        gateway=gateway,
        project_id=project_id,
        actor=actor,
        payload=payload,
    )
    try:
        upstream = await gateway.open_session(
            project_id=project_id,
            actor_id=actor["actor_id"],
            correlation_id=_correlation_id(x_correlation_id),
            session_request=payload.sandbox_payload(),
            context_snapshot=context,
        )
    except (SandboxConfigurationError, SandboxUnavailableError) as error:
        raise _service_error(error) from error
    return _response(upstream)


def _resolve_context(
    *,
    gateway: SandboxControlGateway,
    project_id: str,
    actor: dict[str, Any],
    payload: OpenSandboxSessionRequest,
) -> dict[str, Any] | None:
    if payload.entrypoint == "manual":
        return None
    signer = gateway.context_signer()
    if payload.entrypoint == "graphrag_answer":
        access = core_routes.v2_repository.conversation_access(payload.source_parent_id or "", actor["actor_id"])
        if not access or access.get("project_id") != project_id or not access.get("project_role"):
            raise HTTPException(status_code=404, detail={"code": "ENTITY_NOT_FOUND"})
        message = next(
            (
                item
                for item in core_routes.v2_repository.list_messages(payload.source_parent_id or "")
                if item.get("message_id") == payload.source_resource_id
            ),
            None,
        )
        if not message or message.get("role") != "assistant" or message.get("message_type") != "grounded_answer":
            raise HTTPException(status_code=409, detail={"code": "RESEARCH_CONTEXT_STALE"})
        return signer.graphrag_answer(project_id=project_id, message=message)
    if payload.entrypoint == "validated_candidate":
        gap = core_routes.v2_repository.get_gap(payload.source_resource_id or "")
        if not gap or gap.get("project_id") != project_id:
            raise HTTPException(status_code=404, detail={"code": "ENTITY_NOT_FOUND"})
        if gap.get("status") not in {"reviewer_approved", "reviewer_narrowed"}:
            raise HTTPException(status_code=409, detail={"code": "RESEARCH_CONTEXT_NOT_REVIEWED"})
        return signer.discovery_candidate(project_id=project_id, gap=gap)
    raise HTTPException(
        status_code=422,
        detail={"code": "ENTRYPOINT_NOT_AVAILABLE", "entrypoint": payload.entrypoint},
    )


async def proxy_sandbox_request(
    project_id: str,
    sandbox_path: str,
    request: Request,
    actor: Actor,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-Id")] = None,
) -> Response:
    selected = next(
        (rule for rule in _PROXY_RULES if request.method in rule.methods and rule.pattern.fullmatch(sandbox_path)),
        None,
    )
    if selected is None:
        raise HTTPException(status_code=404, detail={"code": "ENTITY_NOT_FOUND"})
    _membership(
        project_id,
        actor,
        mutation=request.method in {"POST", "DELETE"},
        review=selected.review_action,
    )
    gateway = get_sandbox_gateway()
    if selected.mode and not gateway.settings.allows(selected.mode):
        raise _service_error(SandboxConfigurationError("mode disabled"))
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > gateway.settings.max_request_bytes:
        raise HTTPException(status_code=413, detail={"code": "SANDBOX_REQUEST_TOO_LARGE"})
    body = await request.body()
    if len(body) > gateway.settings.max_request_bytes:
        raise HTTPException(status_code=413, detail={"code": "SANDBOX_REQUEST_TOO_LARGE"})
    forwarded = {
        outbound: request.headers[source]
        for source, outbound in (
            ("content-type", "Content-Type"),
            ("accept", "Accept"),
            ("idempotency-key", "Idempotency-Key"),
            ("x-dataset-classification", "X-Dataset-Classification"),
        )
        if source in request.headers
    }
    upstream_path = f"/api/v1/projects/{project_id}/{sandbox_path}"
    try:
        upstream = await gateway.request(
            method=request.method,
            path=upstream_path,
            project_id=project_id,
            actor_id=actor["actor_id"],
            correlation_id=_correlation_id(x_correlation_id),
            body=body,
            forwarded_headers=forwarded,
        )
    except ValueError as error:
        raise HTTPException(status_code=413, detail={"code": "SANDBOX_REQUEST_TOO_LARGE"}) from error
    except (SandboxConfigurationError, SandboxUnavailableError) as error:
        raise _service_error(error) from error
    return _response(upstream)


# Register one APIRoute per HTTP method. A single multi-method route causes
# FastAPI to emit duplicate OpenAPI operation IDs, which breaks generated
# frontend clients even though request dispatch itself still works.
for _method in ("GET", "POST", "DELETE"):
    router.add_api_route(
        "/{sandbox_path:path}",
        proxy_sandbox_request,
        methods=[_method],
        operation_id=f"proxySandbox{_method.title()}",
        name=f"proxy_sandbox_{_method.lower()}",
    )
