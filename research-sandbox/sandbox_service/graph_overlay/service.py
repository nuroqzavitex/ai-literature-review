"""In-memory overlay assessment over a read-only graph snapshot."""

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Protocol

from sandbox_service.domain.errors import (
    GraphOverlayBaseNotQueryable,
    GraphOverlayStale,
    GraphOverlayTypeViolation,
    SandboxModeMismatch,
    SandboxSessionNotFound,
)
from sandbox_service.domain.graph_overlays import (
    CreateGraphOverlayOperationRequest,
    CreateGraphOverlayRequest,
    GraphOverlay,
    GraphOverlayOperation,
    OverlayAssessment,
    OverlayComparison,
    OverlayOperationType,
    OverlayStatus,
)
from sandbox_service.domain.ports import GraphSnapshotReader
from sandbox_service.domain.sessions import SandboxMode, SandboxSessionResponse, SandboxSessionStatus


class GraphOverlayRepository(Protocol):
    async def get_session(
        self, *, project_id: str, session_id: str
    ) -> SandboxSessionResponse | None: ...

    async def save_overlay(self, overlay: GraphOverlay) -> GraphOverlay: ...

    async def get_overlay(
        self, *, project_id: str, session_id: str, overlay_id: str
    ) -> GraphOverlay | None: ...

    async def list_overlays(
        self, *, project_id: str, session_id: str
    ) -> list[GraphOverlay]: ...

    async def save_overlay_operation(self, operation: GraphOverlayOperation) -> GraphOverlayOperation: ...

    async def list_overlay_operations(self, *, overlay_id: str) -> list[GraphOverlayOperation]: ...

    async def save_assessment(self, assessment: OverlayAssessment) -> OverlayAssessment: ...

    async def get_assessment(self, *, overlay_id: str) -> OverlayAssessment | None: ...


class GraphOverlaySandboxService:
    """Stores only a diff and derives temporary projections for each assessment."""

    MAX_HOPS = 2
    MAX_OPERATIONS = 100

    def __init__(self, *, repository: GraphOverlayRepository, graph_reader: GraphSnapshotReader) -> None:
        self._repository = repository
        self._graph_reader = graph_reader

    async def create_overlay(
        self, *, project_id: str, session_id: str, actor_id: str, request: CreateGraphOverlayRequest
    ) -> GraphOverlay:
        await self._load_overlay_session(project_id=project_id, session_id=session_id)
        base = await self._read_base(project_id=project_id, graph_version_id=request.base_graph_version_id, actor_id=actor_id)
        resolved_graph_version_id = str(
            base.get("graph_version_id") or request.base_graph_version_id
        )
        return await self._repository.save_overlay(
            GraphOverlay(
                project_id=project_id,
                session_id=session_id,
                base_graph_version_id=resolved_graph_version_id,
                shared_graph_version_id=request.shared_graph_version_id,
                base_snapshot_hash=self._hash(base),
            )
        )

    async def list_overlays(self, *, project_id: str, session_id: str) -> list[GraphOverlay]:
        """Return persisted overlays for one project-scoped graph session, newest first."""
        await self._load_overlay_session(project_id=project_id, session_id=session_id)
        return await self._repository.list_overlays(project_id=project_id, session_id=session_id)

    async def add_operation(
        self,
        *,
        project_id: str,
        session_id: str,
        overlay_id: str,
        request: CreateGraphOverlayOperationRequest,
    ) -> GraphOverlayOperation:
        overlay = await self._load_overlay(project_id=project_id, session_id=session_id, overlay_id=overlay_id)
        if overlay.status is OverlayStatus.STALE:
            raise GraphOverlayStale("A stale overlay cannot accept new operations")
        operations = await self._repository.list_overlay_operations(overlay_id=overlay_id)
        if len(operations) >= self.MAX_OPERATIONS:
            raise GraphOverlayTypeViolation("Overlay operation limit exceeded")
        operation_payload = request.model_dump()
        operation_payload["proposed_properties"] = {
            **request.proposed_properties,
            "hypothetical": True,
        }
        operation = GraphOverlayOperation(
            overlay_id=overlay_id,
            sequence=len(operations) + 1,
            **operation_payload,
        )
        await self._repository.save_overlay_operation(operation)
        updated = overlay.model_copy(
            update={
                "operation_hash": self._operation_hash([*operations, operation]),
                "status": OverlayStatus.DRAFT,
                "updated_at": datetime.now(UTC),
            }
        )
        await self._repository.save_overlay(updated)
        return operation

    async def assess(
        self, *, project_id: str, session_id: str, overlay_id: str, actor_id: str
    ) -> OverlayAssessment:
        overlay = await self._load_overlay(project_id=project_id, session_id=session_id, overlay_id=overlay_id)
        base = await self._read_base(
            project_id=project_id, graph_version_id=overlay.base_graph_version_id, actor_id=actor_id
        )
        operations = await self._repository.list_overlay_operations(overlay_id=overlay_id)
        operation_hash = self._operation_hash(operations)
        base_projection = self._normalise_projection(base)
        overlay_projection, conflicts, warnings = self._apply_operations(base_projection, operations)
        assessment = OverlayAssessment(
            overlay_id=overlay_id,
            base_graph_version_id=overlay.base_graph_version_id,
            operation_hash=operation_hash,
            newly_reachable_paths=self._newly_reachable_paths(base_projection, overlay_projection),
            conflicts=conflicts,
            missing_evidence=[
                {"operation_id": item.operation_id, "reason": "No evidence references supplied"}
                for item in operations
                if not item.evidence_refs
            ],
            compatibility_warnings=warnings,
            limitations=[
                "Assessment is hypothetical and bounded to directed traversal of two hops.",
                "The base graph snapshot was read-only and no graph rows were modified.",
            ],
        )
        await self._repository.save_assessment(assessment)
        await self._repository.save_overlay(
            overlay.model_copy(
                update={
                    "operation_hash": operation_hash,
                    "status": OverlayStatus.ASSESSED,
                    "updated_at": datetime.now(UTC),
                }
            )
        )
        return assessment

    async def get_comparison(
        self, *, project_id: str, session_id: str, overlay_id: str
    ) -> OverlayComparison:
        overlay = await self._load_overlay(project_id=project_id, session_id=session_id, overlay_id=overlay_id)
        operations = await self._repository.list_overlay_operations(overlay_id=overlay_id)
        assessment = await self._repository.get_assessment(overlay_id=overlay_id)
        if assessment and assessment.operation_hash != self._operation_hash(operations):
            assessment = None
        return OverlayComparison(overlay=overlay, assessment=assessment, operations=operations)

    async def _load_overlay_session(self, *, project_id: str, session_id: str) -> SandboxSessionResponse:
        session = await self._repository.get_session(project_id=project_id, session_id=session_id)
        if session is None:
            raise SandboxSessionNotFound("Sandbox session was not found in this project")
        if session.mode is not SandboxMode.GRAPH_OVERLAY:
            raise SandboxModeMismatch("Graph overlay operations require a graph_overlay session")
        if session.status is SandboxSessionStatus.STALE:
            raise GraphOverlayStale("The sandbox session is stale")
        return session

    async def _load_overlay(self, *, project_id: str, session_id: str, overlay_id: str) -> GraphOverlay:
        await self._load_overlay_session(project_id=project_id, session_id=session_id)
        overlay = await self._repository.get_overlay(
            project_id=project_id, session_id=session_id, overlay_id=overlay_id
        )
        if overlay is None:
            raise SandboxSessionNotFound("Graph overlay was not found in this project session")
        return overlay

    async def _read_base(self, *, project_id: str, graph_version_id: str, actor_id: str) -> dict[str, Any]:
        try:
            result = await self._graph_reader.read_snapshot(
                project_id=project_id, graph_version_id=graph_version_id, actor_id=actor_id
            )
        except Exception as exc:
            raise GraphOverlayBaseNotQueryable("Pinned base graph version is not queryable") from exc
        if not isinstance(result, dict) or not isinstance(result.get("nodes", []), list) or not isinstance(result.get("edges", []), list):
            raise GraphOverlayBaseNotQueryable("Graph snapshot has an invalid read-only shape")
        return result

    @staticmethod
    def _normalise_projection(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        # deepcopy is deliberate: the GraphSnapshotReader output is never modified.
        projection = deepcopy({"nodes": snapshot.get("nodes", []), "edges": snapshot.get("edges", [])})
        for node in projection["nodes"]:
            if "id" not in node:
                node["id"] = node.get("node_id")
        return projection

    def _apply_operations(
        self, base: dict[str, list[dict[str, Any]]], operations: list[GraphOverlayOperation]
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
        projection = deepcopy(base)
        node_ids = {str(node.get("id")) for node in projection["nodes"] if node.get("id") is not None}
        conflicts: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for item in operations:
            if item.operation is OverlayOperationType.ADD_ENTITY:
                node_id = item.source_ref
                if not node_id or node_id in node_ids:
                    conflicts.append({"operation_id": item.operation_id, "reason": "Entity already exists or lacks an id"})
                    continue
                projection["nodes"].append({"id": node_id, "type": item.entity_or_edge_type, **item.proposed_properties})
                node_ids.add(node_id)
            elif item.operation is OverlayOperationType.ADD_EDGE:
                if item.source_ref not in node_ids or item.target_ref not in node_ids:
                    conflicts.append({"operation_id": item.operation_id, "reason": "Edge endpoint is absent from base plus overlay"})
                    continue
                if any(edge.get("source") == item.source_ref and edge.get("target") == item.target_ref and edge.get("type") == item.entity_or_edge_type for edge in projection["edges"]):
                    conflicts.append({"operation_id": item.operation_id, "reason": "Equivalent edge already exists"})
                    continue
                projection["edges"].append({"source": item.source_ref, "target": item.target_ref, "type": item.entity_or_edge_type, **item.proposed_properties})
            elif item.operation is OverlayOperationType.REMOVE_EDGE:
                original = len(projection["edges"])
                projection["edges"] = [
                    edge for edge in projection["edges"]
                    if not (edge.get("source") == item.source_ref and edge.get("target") == item.target_ref and edge.get("type") == item.entity_or_edge_type)
                ]
                if len(projection["edges"]) == original:
                    conflicts.append({"operation_id": item.operation_id, "reason": "Edge to remove does not exist"})
            else:  # replace_property
                target = next((node for node in projection["nodes"] if node.get("id") == item.source_ref), None)
                if target is None:
                    conflicts.append({"operation_id": item.operation_id, "reason": "Entity to update does not exist"})
                    continue
                if not item.proposed_properties or item.proposed_properties == {"hypothetical": True}:
                    warnings.append({"operation_id": item.operation_id, "reason": "No substantive replacement properties supplied"})
                target.update(item.proposed_properties)
        return projection, conflicts, warnings

    def _newly_reachable_paths(
        self, base: dict[str, list[dict[str, Any]]], overlay: dict[str, list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        base_paths = self._paths_up_to_two_hops(base)
        overlay_paths = self._paths_up_to_two_hops(overlay)
        return [
            {"source_ref": source, "target_ref": target, "hops": hops}
            for (source, target), hops in sorted(overlay_paths.items())
            if (source, target) not in base_paths
        ]

    def _paths_up_to_two_hops(self, projection: dict[str, list[dict[str, Any]]]) -> dict[tuple[str, str], int]:
        adjacency: dict[str, set[str]] = {}
        for edge in projection["edges"]:
            source, target = edge.get("source"), edge.get("target")
            if source is not None and target is not None:
                adjacency.setdefault(str(source), set()).add(str(target))
        paths: dict[tuple[str, str], int] = {}
        for source in adjacency:
            frontier = {source}
            visited = {source}
            for hops in range(1, self.MAX_HOPS + 1):
                frontier = {child for parent in frontier for child in adjacency.get(parent, set()) if child not in visited}
                visited.update(frontier)
                for target in frontier:
                    paths[(source, target)] = hops
        return paths

    @staticmethod
    def _hash(value: object) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    def _operation_hash(self, operations: list[GraphOverlayOperation]) -> str:
        canonical = [
            {
                "sequence": item.sequence,
                "operation": item.operation.value,
                "entity_or_edge_type": item.entity_or_edge_type,
                "source_ref": item.source_ref,
                "target_ref": item.target_ref,
                "proposed_properties": item.proposed_properties,
                "rationale": item.rationale,
                "evidence_refs": item.evidence_refs,
                "hypothetical": True,
            }
            for item in sorted(operations, key=lambda value: value.sequence)
        ]
        return self._hash(canonical)
