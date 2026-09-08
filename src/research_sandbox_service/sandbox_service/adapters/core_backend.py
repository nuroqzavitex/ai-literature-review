"""Signed HTTP adapters for the real report-backed graph and core draft ledger."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from sandbox_service.config import SandboxSettings
from sandbox_service.domain.adoption import AdoptionProposal
from sandbox_service.integration.adoption_bridge import (
    AdoptionHandOffRejected,
    AdoptionProposalBridge,
    CoreDraftProposal,
)
from sandbox_service.integration.auth import SignedServiceAuth, canonical_json


class CoreBackendAdapterError(RuntimeError):
    pass


class _CoreBackendClient:
    def __init__(
        self,
        *,
        base_url: str,
        signing_key: bytes,
        key_id: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("SANDBOX_CORE_BACKEND_URL must be an absolute HTTP URL")
        self._base_url = base_url.rstrip("/")
        self._auth = SignedServiceAuth(signing_key=signing_key, key_id=key_id)
        self._timeout = timeout_seconds
        self._transport = transport

    async def request(
        self,
        *,
        method: str,
        path: str,
        project_id: str,
        actor_id: str,
        correlation_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = canonical_json(payload) if payload is not None else b""
        headers = self._auth.sign_bytes(
            method=method,
            path=path,
            body=body,
            project_id=project_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method,
                    self._base_url + path,
                    content=body,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise CoreBackendAdapterError("Core backend is unavailable") from exc
        if response.status_code >= 400:
            message = "Core backend rejected the Sandbox integration request"
            try:
                detail = response.json().get("detail", {})
                message = detail.get("message") or detail.get("code") or message
            except (TypeError, ValueError):
                pass
            raise CoreBackendAdapterError(str(message))
        value = response.json()
        if not isinstance(value, dict):
            raise CoreBackendAdapterError("Core backend returned an invalid response")
        return value


class CoreBackendGraphSnapshotReader:
    def __init__(self, client: _CoreBackendClient) -> None:
        self._client = client

    async def read_snapshot(
        self, *, project_id: str, graph_version_id: str, actor_id: str
    ) -> dict[str, Any]:
        project_ref = quote(project_id, safe="")
        version_ref = quote(graph_version_id, safe="")
        return await self._client.request(
            method="GET",
            path=(
                f"/internal/v1/sandbox/projects/{project_ref}/"
                f"graph-snapshots/{version_ref}"
            ),
            project_id=project_id,
            actor_id=actor_id,
            correlation_id=f"graph-snapshot:{graph_version_id}",
        )


class CoreBackendAdoptionRevalidator:
    def __init__(self, client: _CoreBackendClient) -> None:
        self._client = client

    async def is_current_and_authorized(
        self,
        *,
        project_id: str,
        proposal: AdoptionProposal,
        actor_id: str,
        source_bundle: dict[str, Any],
    ) -> bool:
        project_ref = quote(project_id, safe="")
        try:
            response = await self._client.request(
                method="POST",
                path=f"/internal/v1/sandbox/projects/{project_ref}/adoption-preflight",
                project_id=project_id,
                actor_id=actor_id,
                correlation_id=f"adoption-preflight:{proposal.proposal_id}",
                payload={
                    "sandbox_proposal_id": proposal.proposal_id,
                    "source_type": proposal.source_type.value,
                    "base_graph_version_id": source_bundle.get("base_graph_version_id"),
                },
            )
        except CoreBackendAdapterError:
            return False
        return response.get("current") is True


class CoreBackendDraftProposalSink:
    def __init__(self, client: _CoreBackendClient) -> None:
        self._client = client

    async def create_draft(
        self,
        proposal: CoreDraftProposal,
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> str:
        del idempotency_key  # Core deduplicates by immutable sandbox_proposal_id.
        project_ref = quote(proposal.project_id, safe="")
        try:
            response = await self._client.request(
                method="POST",
                path=f"/internal/v1/sandbox/projects/{project_ref}/adoption-drafts",
                project_id=proposal.project_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                payload={
                    "sandbox_proposal_id": proposal.sandbox_proposal_id,
                    "source_type": proposal.source_type,
                    "source_id": proposal.source_id,
                    "rationale": proposal.rationale,
                    "source_hash": proposal.source_hash,
                    "source_bundle": proposal.source_bundle,
                },
            )
        except CoreBackendAdapterError as exc:
            raise AdoptionHandOffRejected(str(exc)) from exc
        draft_id = response.get("core_draft_id")
        if not isinstance(draft_id, str) or not draft_id:
            raise AdoptionHandOffRejected("Core backend did not return a draft id")
        return draft_id


def _client_from_settings(
    *, transport: httpx.AsyncBaseTransport | None = None
) -> _CoreBackendClient:
    settings = SandboxSettings()
    if settings.core_backend_url is None or settings.service_auth_key is None:
        raise RuntimeError(
            "Core backend adapters require SANDBOX_CORE_BACKEND_URL and SANDBOX_SERVICE_AUTH_KEY"
        )
    return _CoreBackendClient(
        base_url=settings.core_backend_url,
        signing_key=settings.service_auth_key.get_secret_value().encode("utf-8"),
        key_id=settings.service_auth_key_id,
        timeout_seconds=settings.core_backend_timeout_seconds,
        transport=transport,
    )


def create_core_backend_graph_snapshot_reader() -> CoreBackendGraphSnapshotReader:
    return CoreBackendGraphSnapshotReader(_client_from_settings())


def create_core_backend_adoption_bridge() -> AdoptionProposalBridge:
    client = _client_from_settings()
    return AdoptionProposalBridge(
        sink=CoreBackendDraftProposalSink(client),
        revalidator=CoreBackendAdoptionRevalidator(client),
    )
