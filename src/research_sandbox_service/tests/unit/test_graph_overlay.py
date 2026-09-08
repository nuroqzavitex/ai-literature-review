from copy import deepcopy

import pytest
from sandbox_service.adoption import AdoptionProposalService
from sandbox_service.domain.adoption import (
    AdoptionProposalStatus,
    AdoptionSourceType,
    CreateAdoptionProposalRequest,
    ReviewAdoptionProposalRequest,
)
from sandbox_service.domain.graph_overlays import (
    CreateGraphOverlayOperationRequest,
    CreateGraphOverlayRequest,
)
from sandbox_service.domain.sessions import CreateSandboxSessionRequest
from sandbox_service.graph_overlay import GraphOverlaySandboxService
from sandbox_service.repositories.memory import InMemorySandboxSessionRepository
from sandbox_service.session_service import SandboxSessionService
from tests.fakes import FakeGraphSnapshotReader


@pytest.mark.asyncio
async def test_overlay_uses_bounded_projection_and_never_mutates_base_snapshot() -> None:
    base_snapshot = {
        "graph_version_id": "graph-v1",
        "nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
        "edges": [{"source": "A", "target": "B", "type": "supports"}],
    }
    original_snapshot = deepcopy(base_snapshot)
    repository = InMemorySandboxSessionRepository()
    session = await SandboxSessionService(repository=repository).create_session(
        project_id="project-a",
        actor_id="researcher-a",
        request=CreateSandboxSessionRequest(
            mode="graph_overlay", entrypoint="manual", title="Overlay test"
        ),
    )
    reader = FakeGraphSnapshotReader({
        ("project-a", "current"): base_snapshot,
        ("project-a", "graph-v1"): base_snapshot,
    })
    service = GraphOverlaySandboxService(repository=repository, graph_reader=reader)

    overlay = await service.create_overlay(
        project_id="project-a",
        session_id=session.session_id,
        actor_id="researcher-a",
        request=CreateGraphOverlayRequest(base_graph_version_id="current"),
    )
    assert overlay.base_graph_version_id == "graph-v1"
    assert await service.list_overlays(project_id="project-a", session_id=session.session_id) == [overlay]
    operation = await service.add_operation(
        project_id="project-a",
        session_id=session.session_id,
        overlay_id=overlay.overlay_id,
        request=CreateGraphOverlayOperationRequest(
            operation="add_edge",
            entity_or_edge_type="supports",
            source_ref="B",
            target_ref="C",
            rationale="Test a hypothetical relation",
            evidence_refs=["evidence-1"],
        ),
    )
    assessment = await service.assess(
        project_id="project-a",
        session_id=session.session_id,
        overlay_id=overlay.overlay_id,
        actor_id="researcher-a",
    )
    comparison = await service.get_comparison(
        project_id="project-a", session_id=session.session_id, overlay_id=overlay.overlay_id
    )

    assert operation.hypothetical is True
    assert operation.proposed_properties["hypothetical"] is True
    assert {"source_ref": "A", "target_ref": "C", "hops": 2} in assessment.newly_reachable_paths
    assert assessment.conflicts == []
    assert comparison.assessment == assessment
    assert base_snapshot == original_snapshot
    assert reader.calls == [
        {"project_id": "project-a", "graph_version_id": "current"},
        {"project_id": "project-a", "graph_version_id": "graph-v1"},
    ]

    adoption = AdoptionProposalService(repository=repository)
    proposal = await adoption.create(
        project_id="project-a",
        session_id=session.session_id,
        actor_id="researcher-a",
        request=CreateAdoptionProposalRequest(
            source_type=AdoptionSourceType.OVERLAY_ASSESSMENT,
            source_id=assessment.assessment_id,
            rationale="Request a separate core review only.",
        ),
    )
    in_review = await adoption.review(
        project_id="project-a",
        proposal_id=proposal.proposal_id,
        reviewer_id="reviewer-a",
        request=ReviewAdoptionProposalRequest(decision=AdoptionProposalStatus.IN_REVIEW),
    )
    approved = await adoption.review(
        project_id="project-a",
        proposal_id=proposal.proposal_id,
        reviewer_id="reviewer-a",
        request=ReviewAdoptionProposalRequest(
            decision=AdoptionProposalStatus.APPROVED, reason="Hand off as draft only"
        ),
    )
    assert in_review.status is AdoptionProposalStatus.IN_REVIEW
    assert approved.status is AdoptionProposalStatus.APPROVED
    assert repository.adoption_decisions[-1].decision is AdoptionProposalStatus.APPROVED
    assert base_snapshot == original_snapshot


@pytest.mark.asyncio
async def test_overlay_assessment_records_conflicts_without_writing_the_base_graph() -> None:
    base_snapshot = {"nodes": [{"id": "A"}], "edges": []}
    repository = InMemorySandboxSessionRepository()
    session = await SandboxSessionService(repository=repository).create_session(
        project_id="project-a",
        actor_id="researcher-a",
        request=CreateSandboxSessionRequest(
            mode="graph_overlay", entrypoint="manual", title="Conflict overlay"
        ),
    )
    service = GraphOverlaySandboxService(
        repository=repository,
        graph_reader=FakeGraphSnapshotReader({("project-a", "graph-v1"): base_snapshot}),
    )
    overlay = await service.create_overlay(
        project_id="project-a",
        session_id=session.session_id,
        actor_id="researcher-a",
        request=CreateGraphOverlayRequest(base_graph_version_id="graph-v1"),
    )
    await service.add_operation(
        project_id="project-a",
        session_id=session.session_id,
        overlay_id=overlay.overlay_id,
        request=CreateGraphOverlayOperationRequest(
            operation="add_edge",
            entity_or_edge_type="supports",
            source_ref="A",
            target_ref="missing",
            rationale="Deliberately invalid endpoint",
        ),
    )

    assessment = await service.assess(
        project_id="project-a",
        session_id=session.session_id,
        overlay_id=overlay.overlay_id,
        actor_id="researcher-a",
    )

    assert assessment.conflicts[0]["reason"] == "Edge endpoint is absent from base plus overlay"
    assert assessment.missing_evidence[0]["reason"] == "No evidence references supplied"
    assert base_snapshot == {"nodes": [{"id": "A"}], "edges": []}
