from __future__ import annotations

import httpx
import pytest

from sandbox_service.adapters.core_backend import (
    CoreBackendAdoptionRevalidator,
    CoreBackendDraftProposalSink,
    CoreBackendGraphSnapshotReader,
    _CoreBackendClient,
)
from sandbox_service.domain.adoption import AdoptionProposal
from sandbox_service.integration.adoption_bridge import CoreDraftProposal


def client(handler) -> _CoreBackendClient:
    return _CoreBackendClient(
        base_url="http://core.test",
        signing_key=b"test-service-auth-key-that-is-at-least-32-bytes",
        key_id="test-key",
        timeout_seconds=2,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_graph_reader_uses_signed_internal_http_and_returns_real_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/graph-snapshots/current")
        assert request.headers["X-Sandbox-Key-Id"] == "test-key"
        assert request.headers["X-Sandbox-Project-Id"] == "project-a"
        assert request.headers["X-Sandbox-Actor-Id"] == "actor-a"
        assert request.headers["X-Sandbox-Signature"]
        return httpx.Response(200, json={
            "graph_version_id": "report-v1", "nodes": [], "edges": [], "snapshot_hash": "hash-a"
        })

    snapshot = await CoreBackendGraphSnapshotReader(client(handler)).read_snapshot(
        project_id="project-a", graph_version_id="current", actor_id="actor-a"
    )
    assert snapshot["graph_version_id"] == "report-v1"


@pytest.mark.asyncio
async def test_adoption_preflight_and_sink_use_core_draft_boundary() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/adoption-preflight"):
            return httpx.Response(200, json={"current": True})
        return httpx.Response(201, json={"core_draft_id": "act-core-1", "status": "draft_created"})

    backend = client(handler)
    proposal = AdoptionProposal(
        project_id="project-a", session_id="session-a", source_type="overlay_assessment",
        source_id="assessment-a", rationale="reviewed", requested_by="actor-a", status="approved",
    )
    bundle = {"base_graph_version_id": "report-v1"}
    assert await CoreBackendAdoptionRevalidator(backend).is_current_and_authorized(
        project_id="project-a", proposal=proposal, actor_id="actor-a", source_bundle=bundle
    )
    draft_id = await CoreBackendDraftProposalSink(backend).create_draft(
        CoreDraftProposal(
            project_id="project-a", source_system="research-sandbox",
            sandbox_proposal_id=proposal.proposal_id, source_type="overlay_assessment",
            source_id="assessment-a", rationale="reviewed", base_graph_version_id="report-v1",
            source_hash="hash-a", source_bundle=bundle,
        ),
        actor_id="actor-a", correlation_id="corr-a",
    )
    assert draft_id == "act-core-1"
    assert paths == [
        "/internal/v1/sandbox/projects/project-a/adoption-preflight",
        "/internal/v1/sandbox/projects/project-a/adoption-drafts",
    ]
