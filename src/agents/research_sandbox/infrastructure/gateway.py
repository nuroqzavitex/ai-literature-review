"""Server-only BFF client for the independently deployed Research Sandbox.

No browser credential or actor field is forwarded. The caller first performs core
authentication and project authorization; this adapter then signs the exact
outbound bytes with the server-held service key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from src.config import Settings

SandboxMode = Literal["hypothesis", "graph_overlay", "data_analysis"]

LOGGER = logging.getLogger(__name__)
_AI_MUTATION_SUFFIXES = ("/hypotheses", "/experiments", "/analysis-plans", "/runs")


class SandboxUnavailableError(RuntimeError):
    pass


class SandboxConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendSandboxGatewaySettings:
    enabled: bool
    demo_mode: bool
    hypothesis_enabled: bool
    graph_overlay_enabled: bool
    data_analysis_enabled: bool
    ai_enabled: bool
    graph_context_enabled: bool
    result_interpretation_enabled: bool
    control_url: str
    service_auth_key: str
    service_auth_key_id: str
    context_signing_key: str
    context_signing_key_id: str
    timeout_seconds: float
    max_request_bytes: int
    max_response_bytes: int
    ai_timeout_seconds: float = 180.0

    def allows(self, mode: str) -> bool:
        return self.enabled and {
            "hypothesis": self.hypothesis_enabled,
            "graph_overlay": self.graph_overlay_enabled,
            "data_analysis": self.data_analysis_enabled,
        }.get(mode, False)

    @property
    def configured(self) -> bool:
        return bool(self.control_url and len(self.service_auth_key.encode("utf-8")) >= 32)


@dataclass(frozen=True)
class SandboxUpstreamResponse:
    status_code: int
    content: bytes
    headers: Mapping[str, str]


def sandbox_gateway_settings(settings: Settings) -> BackendSandboxGatewaySettings:
    return BackendSandboxGatewaySettings(
        enabled=settings.sandbox_enabled,
        demo_mode=settings.sandbox_demo_mode,
        hypothesis_enabled=settings.sandbox_hypothesis_enabled,
        graph_overlay_enabled=settings.sandbox_graph_overlay_enabled,
        data_analysis_enabled=settings.sandbox_data_analysis_enabled,
        ai_enabled=settings.sandbox_ai_enabled,
        graph_context_enabled=settings.sandbox_graph_context_enabled,
        result_interpretation_enabled=settings.sandbox_result_interpretation_enabled,
        control_url=settings.sandbox_control_url,
        service_auth_key=settings.sandbox_service_auth_key,
        service_auth_key_id=settings.sandbox_service_auth_key_id,
        context_signing_key=settings.sandbox_context_signing_key,
        context_signing_key_id=settings.sandbox_context_signing_key_id,
        timeout_seconds=settings.sandbox_request_timeout_seconds,
        max_request_bytes=settings.sandbox_proxy_max_request_bytes,
        max_response_bytes=settings.sandbox_proxy_max_response_bytes,
        ai_timeout_seconds=settings.sandbox_ai_request_timeout_seconds,
    )


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class SignedSandboxRequestAuth:
    """HMAC binding for raw JSON, multipart, and artifact requests."""

    def __init__(self, *, key: str, key_id: str, max_age_seconds: int = 300) -> None:
        encoded = key.encode("utf-8")
        if len(encoded) < 32:
            raise SandboxConfigurationError("sandbox service-auth key is not configured")
        self._key = encoded
        self._key_id = key_id
        self._max_age_seconds = max_age_seconds
        self._seen_nonces: dict[str, int] = {}
        self._nonce_lock = Lock()

    def sign(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        project_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> dict[str, str]:
        timestamp = str(int(datetime.now(UTC).timestamp()))
        nonce = secrets.token_urlsafe(24)
        digest = hashlib.sha256(body).hexdigest()
        canonical = "\n".join(
            (
                method.upper(),
                path,
                digest,
                project_id,
                actor_id,
                correlation_id,
                timestamp,
                nonce,
            )
        )
        signature = hmac.new(self._key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "X-Sandbox-Key-Id": self._key_id,
            "X-Sandbox-Timestamp": timestamp,
            "X-Sandbox-Nonce": nonce,
            "X-Sandbox-Project-Id": project_id,
            "X-Sandbox-Actor-Id": actor_id,
            "X-Correlation-Id": correlation_id,
            "X-Sandbox-Content-SHA256": digest,
            "X-Sandbox-Signature": signature,
        }

    def verify_bytes(
        self,
        *,
        method: str,
        path: str,
        body: bytes,
        headers: Mapping[str, str],
        now: datetime | None = None,
    ) -> tuple[str, str, str]:
        """Verify a Sandbox-to-core request using the same byte-bound contract."""

        normalized = {name.lower(): value for name, value in headers.items()}
        required = (
            "x-sandbox-key-id",
            "x-sandbox-timestamp",
            "x-sandbox-nonce",
            "x-sandbox-project-id",
            "x-sandbox-actor-id",
            "x-correlation-id",
            "x-sandbox-content-sha256",
            "x-sandbox-signature",
        )
        if any(name not in normalized for name in required):
            raise SandboxConfigurationError("missing signed service-auth header")
        if normalized["x-sandbox-key-id"] != self._key_id:
            raise SandboxConfigurationError("unknown service-auth key id")
        try:
            signed_at = int(normalized["x-sandbox-timestamp"])
        except ValueError as exc:
            raise SandboxConfigurationError("invalid service-auth timestamp") from exc
        current = int((now or datetime.now(UTC)).timestamp())
        if abs(current - signed_at) > self._max_age_seconds:
            raise SandboxConfigurationError("expired service-auth request")
        digest = hashlib.sha256(body).hexdigest()
        if not hmac.compare_digest(normalized["x-sandbox-content-sha256"], digest):
            raise SandboxConfigurationError("service-auth content digest mismatch")
        canonical = "\n".join(
            (
                method.upper(),
                path,
                digest,
                normalized["x-sandbox-project-id"],
                normalized["x-sandbox-actor-id"],
                normalized["x-correlation-id"],
                normalized["x-sandbox-timestamp"],
                normalized["x-sandbox-nonce"],
            )
        )
        expected = hmac.new(self._key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(normalized["x-sandbox-signature"], expected):
            raise SandboxConfigurationError("invalid service-auth signature")
        nonce = normalized["x-sandbox-nonce"]
        with self._nonce_lock:
            self._seen_nonces = {value: expiry for value, expiry in self._seen_nonces.items() if expiry > current}
            if nonce in self._seen_nonces:
                raise SandboxConfigurationError("replayed service-auth request")
            self._seen_nonces[nonce] = signed_at + self._max_age_seconds + 1
        return (
            normalized["x-sandbox-project-id"],
            normalized["x-sandbox-actor-id"],
            normalized["x-correlation-id"],
        )


class CoreResearchContextSigner:
    """Build minimal immutable context from records already authorized by core."""

    def __init__(self, *, key: str, key_id: str) -> None:
        encoded = key.encode("utf-8")
        if len(encoded) < 32:
            raise SandboxConfigurationError("sandbox context-signing key is not configured")
        self._key = encoded
        self._key_id = key_id

    def graphrag_answer(self, *, project_id: str, message: Mapping[str, Any]) -> dict[str, Any]:
        evidence_refs = [
            {
                "citation_id": item.get("citation_id"),
                "paper_id": item.get("paper_id"),
                "evidence_id": item.get("evidence_id"),
                "report_version_id": item.get("report_version_id"),
            }
            for item in message.get("citations", [])
            if item.get("valid")
        ]
        return self._build(
            project_id=project_id,
            source_type="graphrag_answer",
            source_resource_id=str(message["message_id"]),
            graph_version_id=message.get("report_version_id"),
            evidence_refs=evidence_refs,
            limitations=list(message.get("limitations") or []),
            source_status="reviewed",
        )

    def discovery_candidate(self, *, project_id: str, gap: Mapping[str, Any]) -> dict[str, Any]:
        raw_refs = [
            *(gap.get("coverage") or []),
            *(gap.get("counterevidence_paper_ids") or []),
        ]
        evidence_refs: list[dict[str, Any]] = []
        for value in raw_refs:
            if isinstance(value, str) and value:
                evidence_refs.append(
                    {
                        "evidence_id": value,
                        "report_version_id": gap.get("report_version_id"),
                    }
                )
            elif isinstance(value, Mapping):
                reference = {
                    key: value.get(key)
                    for key in ("paper_id", "evidence_id", "mentioned")
                    if value.get(key) is not None
                }
                if reference:
                    evidence_refs.append(
                        {
                            **reference,
                            "report_version_id": gap.get("report_version_id"),
                        }
                    )
        return self._build(
            project_id=project_id,
            source_type="validated_candidate",
            source_resource_id=str(gap["gap_id"]),
            graph_version_id=gap.get("report_version_id"),
            discovery_run_id=gap.get("report_version_id"),
            candidate_id=str(gap["gap_id"]),
            evidence_refs=evidence_refs,
            limitations=["Discovery candidate remains hypothetical until Sandbox review."],
            source_status="validated_candidate",
        )

    def _build(self, **values: Any) -> dict[str, Any]:
        created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        provisional: dict[str, Any] = {
            "schema_version": "research_context.v1",
            "project_id": values["project_id"],
            "source_type": values["source_type"],
            "source_resource_id": values["source_resource_id"],
            "graph_version_id": values.get("graph_version_id"),
            "shared_graph_version_id": None,
            "discovery_run_id": values.get("discovery_run_id"),
            "candidate_id": values.get("candidate_id"),
            "experiment_proposal_id": None,
            "research_question_suggestion": None,
            "objective_suggestion": None,
            "method_suggestions": [],
            "dataset_requirements": [],
            "evaluation_metric_suggestions": [],
            "evidence_refs": values.get("evidence_refs") or [],
            "limitations": values.get("limitations") or [],
            "source_status": values["source_status"],
        }
        content_hash = hashlib.sha256(canonical_json(provisional)).hexdigest()
        snapshot = {
            **provisional,
            # The durable sandbox schema stores context_id as PostgreSQL UUID.
            # Keep the ID deterministic without using the former ``ctx_``
            # prefix, which PostgreSQL correctly rejected for contextual
            # sessions while manual sessions continued to work.
            "context_id": str(UUID(hex=content_hash[:32])),
            "content_hash": content_hash,
            "signing_key_id": self._key_id,
            "created_at": created_at,
        }
        signature = hmac.new(self._key, canonical_json(snapshot), hashlib.sha256).hexdigest()
        return {**snapshot, "signature": signature}


class SandboxControlGateway:
    """Allowlisted transport; construction performs no network request."""

    INTERNAL_SESSION_PATH = "/internal/v1/gateway/sessions"

    def __init__(
        self,
        *,
        settings: BackendSandboxGatewaySettings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport

    def capabilities(self) -> dict[str, Any]:
        configured = self.settings.configured
        enabled = self.settings.enabled
        return {
            "schema_version": "sandbox_capabilities.v1",
            "enabled": enabled,
            "demo_mode": enabled and self.settings.demo_mode,
            "available": enabled and configured,
            "modes": {
                "hypothesis": self.settings.allows("hypothesis"),
                "graph_overlay": self.settings.allows("graph_overlay"),
                "data_analysis": self.settings.allows("data_analysis"),
            },
            "ai_enabled": enabled and self.settings.ai_enabled,
            "graph_context_enabled": enabled and self.settings.graph_context_enabled,
            "result_interpretation_enabled": (
                enabled and self.settings.ai_enabled and self.settings.result_interpretation_enabled
            ),
            "supported_dataset_formats": ["csv", "xlsx", "parquet"],
            "max_dataset_bytes": 50 * 1024 * 1024,
            "max_overlay_hops": 2,
            "run_polling_supported": True,
            "reason": ("disabled" if not enabled else "not_configured" if not configured else None),
        }

    async def open_session(
        self,
        *,
        project_id: str,
        actor_id: str,
        correlation_id: str,
        session_request: Mapping[str, Any],
        context_snapshot: Mapping[str, Any] | None,
    ) -> SandboxUpstreamResponse:
        mode = str(session_request.get("mode", ""))
        if not self.settings.allows(mode):
            raise SandboxConfigurationError("requested Sandbox mode is disabled")
        payload = {
            "request": dict(session_request),
            "context_snapshot": dict(context_snapshot) if context_snapshot else None,
        }
        body = canonical_json(payload)
        return await self.request(
            method="POST",
            path=self.INTERNAL_SESSION_PATH,
            project_id=project_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            body=body,
            forwarded_headers={"Content-Type": "application/json"},
        )

    async def request(
        self,
        *,
        method: str,
        path: str,
        project_id: str,
        actor_id: str,
        correlation_id: str,
        body: bytes = b"",
        forwarded_headers: Mapping[str, str] | None = None,
    ) -> SandboxUpstreamResponse:
        self._validate_configuration()
        if len(body) > self.settings.max_request_bytes:
            raise ValueError("Sandbox proxy request exceeds the configured limit")
        auth = SignedSandboxRequestAuth(
            key=self.settings.service_auth_key,
            key_id=self.settings.service_auth_key_id,
        )
        headers = auth.sign(
            method=method,
            path=path,
            body=body,
            project_id=project_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        headers.update(forwarded_headers or {})
        read_timeout = self._read_timeout(method=method, path=path)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=self.settings.timeout_seconds,
                    read=read_timeout,
                    write=read_timeout,
                    pool=self.settings.timeout_seconds,
                ),
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method,
                    self.settings.control_url.rstrip("/") + path,
                    content=body,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            LOGGER.warning(
                "sandbox_gateway_http_error method=%s path=%s correlation_id=%s error_type=%s read_timeout_seconds=%s",
                method,
                path,
                correlation_id,
                type(exc).__name__,
                read_timeout,
            )
            raise SandboxUnavailableError("Sandbox Control Service is unavailable") from exc
        if len(response.content) > self.settings.max_response_bytes:
            raise SandboxUnavailableError("Sandbox response exceeds the BFF limit")
        if response.status_code >= 500:
            safe_error: Any = None
            try:
                payload = response.json()
                if isinstance(payload, Mapping):
                    detail = payload.get("detail", payload)
                    if isinstance(detail, Mapping):
                        safe_error = {
                            key: detail.get(key)
                            for key in ("error_code", "code", "message")
                            if detail.get(key) is not None
                        }
                    elif isinstance(detail, str):
                        safe_error = detail[:500]
            except (ValueError, UnicodeDecodeError):
                safe_error = None
            LOGGER.error(
                "sandbox_gateway_upstream_error method=%s path=%s correlation_id=%s upstream_status=%s safe_error=%r",
                method,
                path,
                correlation_id,
                response.status_code,
                safe_error,
            )
            raise SandboxUnavailableError("Sandbox Control Service is unavailable")
        safe_headers = {
            name: response.headers[name]
            for name in (
                "content-type",
                "content-disposition",
                "cache-control",
                "etag",
                "retry-after",
                "x-content-type-options",
            )
            if name in response.headers
        }
        return SandboxUpstreamResponse(
            status_code=response.status_code,
            content=response.content,
            headers=safe_headers,
        )

    def _read_timeout(self, *, method: str, path: str) -> float:
        if method.upper() == "POST" and path.endswith(_AI_MUTATION_SUFFIXES):
            return self.settings.ai_timeout_seconds
        return self.settings.timeout_seconds

    def context_signer(self) -> CoreResearchContextSigner:
        return CoreResearchContextSigner(
            key=self.settings.context_signing_key,
            key_id=self.settings.context_signing_key_id,
        )

    def _validate_configuration(self) -> None:
        if not self.settings.enabled or not self.settings.configured:
            raise SandboxConfigurationError("Sandbox integration is disabled or not configured")
        parsed = urlsplit(self.settings.control_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise SandboxConfigurationError("SANDBOX_CONTROL_URL is invalid")


def build_sandbox_gateway(
    *, settings: Settings, transport: httpx.AsyncBaseTransport | None = None, **_: Any
) -> SandboxControlGateway:
    """Compatibility factory; still performs no I/O until an explicit BFF action."""
    return SandboxControlGateway(settings=sandbox_gateway_settings(settings), transport=transport)


def new_correlation_id() -> str:
    return str(uuid4())
