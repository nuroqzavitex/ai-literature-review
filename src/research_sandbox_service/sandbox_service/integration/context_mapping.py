"""Map core GraphRAG/Discovery records into minimal signed pinned contexts."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from sandbox_service.domain.sessions import ResearchContextSnapshot, SandboxEntrypoint
from sandbox_service.integration.auth import ContextSnapshotSigner, ServiceAuthError, canonical_json


class ContextMappingError(ValueError):
    pass


class ResearchContextMapper:
    def __init__(self, *, snapshot_signer: ContextSnapshotSigner) -> None:
        self._signer = snapshot_signer

    def graphrag_answer(self, *, project_id: str, answer_id: str, graph_version_id: str, evidence_refs: list[dict[str, Any]], research_question: str | None = None, limitations: list[str] | None = None) -> ResearchContextSnapshot:
        return self._build(
            project_id=project_id,
            source_type=SandboxEntrypoint.GRAPHRAG_ANSWER,
            source_resource_id=answer_id,
            graph_version_id=graph_version_id,
            evidence_refs=evidence_refs,
            research_question_suggestion=research_question,
            limitations=limitations or [],
            source_status="reviewed",
        )

    def discovery_candidate(self, *, project_id: str, candidate_id: str, discovery_run_id: str, graph_version_id: str | None, evidence_refs: list[dict[str, Any]], limitations: list[str]) -> ResearchContextSnapshot:
        return self._build(
            project_id=project_id,
            source_type=SandboxEntrypoint.VALIDATED_CANDIDATE,
            source_resource_id=candidate_id,
            graph_version_id=graph_version_id,
            discovery_run_id=discovery_run_id,
            candidate_id=candidate_id,
            evidence_refs=evidence_refs,
            limitations=limitations,
            source_status="validated_candidate",
        )

    def experiment_proposal(self, *, project_id: str, proposal_id: str, proposal_version: str, evidence_refs: list[dict[str, Any]], limitations: list[str] | None = None) -> ResearchContextSnapshot:
        return self._build(
            project_id=project_id,
            source_type=SandboxEntrypoint.EXPERIMENT_PROPOSAL,
            source_resource_id=proposal_id,
            experiment_proposal_id=proposal_id,
            evidence_refs=evidence_refs,
            limitations=limitations or [],
            method_suggestions=[f"proposal_version:{proposal_version}"],
            source_status="reviewed",
        )

    def verify(self, snapshot: ResearchContextSnapshot, *, project_id: str, entrypoint: SandboxEntrypoint, source_resource_id: str) -> ResearchContextSnapshot:
        if snapshot.project_id != project_id:
            raise ContextMappingError("context snapshot project_id does not match authenticated project")
        if snapshot.source_type is not entrypoint or snapshot.source_resource_id != source_resource_id:
            raise ContextMappingError("context snapshot source does not match requested entrypoint")
        expected_hash = self._content_hash(snapshot)
        if snapshot.content_hash != expected_hash:
            raise ContextMappingError("context snapshot content hash is stale or tampered")
        try:
            self._signer.verify(snapshot)
        except ServiceAuthError as exc:
            raise ContextMappingError(str(exc)) from exc
        return snapshot

    def _build(self, *, project_id: str, source_type: SandboxEntrypoint, source_resource_id: str, graph_version_id: str | None = None, shared_graph_version_id: str | None = None, discovery_run_id: str | None = None, candidate_id: str | None = None, experiment_proposal_id: str | None = None, research_question_suggestion: str | None = None, objective_suggestion: str | None = None, method_suggestions: list[str] | None = None, dataset_requirements: list[str] | None = None, evaluation_metric_suggestions: list[str] | None = None, evidence_refs: list[dict[str, Any]] | None = None, limitations: list[str] | None = None, source_status: str = "reviewed") -> ResearchContextSnapshot:
        if not project_id or not source_resource_id:
            raise ContextMappingError("project_id and source_resource_id are required")
        provisional = ResearchContextSnapshot(
            project_id=project_id,
            source_type=source_type,
            source_resource_id=source_resource_id,
            graph_version_id=graph_version_id,
            shared_graph_version_id=shared_graph_version_id,
            discovery_run_id=discovery_run_id,
            candidate_id=candidate_id,
            experiment_proposal_id=experiment_proposal_id,
            research_question_suggestion=research_question_suggestion,
            objective_suggestion=objective_suggestion,
            method_suggestions=method_suggestions or [],
            dataset_requirements=dataset_requirements or [],
            evaluation_metric_suggestions=evaluation_metric_suggestions or [],
            evidence_refs=evidence_refs or [],
            limitations=limitations or [],
            source_status=source_status,
            content_hash="pending",
            created_at=datetime.now(timezone.utc),
        )
        content_hash = self._content_hash(provisional)
        # S0001 deliberately stores context identifiers as UUID. Derive one
        # from the signed content hash so repeated hand-offs stay idempotent
        # and remain valid for the durable PostgreSQL repository.
        deterministic_id = str(UUID(hex=content_hash[:32]))
        return self._signer.sign(provisional.model_copy(update={"context_id": deterministic_id, "content_hash": content_hash}))

    @staticmethod
    def _content_hash(snapshot: ResearchContextSnapshot) -> str:
        payload = snapshot.model_dump(mode="json", exclude={"context_id", "content_hash", "created_at", "signing_key_id", "signature"})
        return hashlib.sha256(canonical_json(payload)).hexdigest()


def sandbox_action_metadata(snapshot: ResearchContextSnapshot) -> dict[str, str]:
    """UI metadata only; it carries no context payload or authority."""
    action = "open_in_sandbox" if snapshot.source_type is SandboxEntrypoint.GRAPHRAG_ANSWER else "test_this_candidate"
    return {
        "action": action,
        "project_id": snapshot.project_id,
        "entrypoint": snapshot.source_type.value,
        "source_resource_id": snapshot.source_resource_id or "",
        "context_id": snapshot.context_id,
    }
