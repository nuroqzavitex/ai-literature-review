"""Core-owned graph projection and Sandbox adoption application service."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

SOURCE_SYSTEM = "research-sandbox"
ADOPTION_ACTION_TYPE = "adopt_sandbox_proposal"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class CoreSandboxRepository(Protocol):
    def membership(self, project_id: str, actor_id: str) -> dict[str, Any] | None: ...

    def get_project(self, project_id: str) -> dict[str, Any] | None: ...

    def get_report_version(self, project_id: str, version_id: str) -> dict[str, Any] | None: ...

    def list_gaps(self, project_id: str, version_id: str | None = None) -> list[dict[str, Any]]: ...

    def create_external_action(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]: ...

    def audit(
        self,
        project_id: str,
        actor_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        base_version_id: str | None = None,
        result_version_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...


class CoreSandboxIntegrationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:{str(value)}"


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (str(edge["source"]), str(edge["target"]), str(edge["type"]))


def project_report_graph(*, project_id: str, version: dict[str, Any], gaps: list[dict[str, Any]]) -> dict[str, Any]:
    """Project an immutable report into the generic graph-overlay shape."""

    report = version.get("report") or {}
    graph_version_id = str(version["report_version_id"])
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_node(node_id: str, node_type: str, **properties: Any) -> None:
        nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            **{key: value for key, value in properties.items() if value is not None},
        }

    def add_edge(source: str, target: str, edge_type: str, **properties: Any) -> None:
        edge = {
            "source": source,
            "target": target,
            "type": edge_type,
            **{key: value for key, value in properties.items() if value is not None},
        }
        edges[_edge_key(edge)] = edge

    report_ref = _ref("report", graph_version_id)
    add_node(
        report_ref,
        "ReportVersion",
        name=f"Report version {version.get('version_number', graph_version_id)}",
        version_number=version.get("version_number"),
        corpus_hash=version.get("corpus_hash"),
    )

    for paper in report.get("papers", []):
        paper_id = paper.get("paper_id") or paper.get("id")
        if not paper_id:
            continue
        paper_ref = _ref("paper", paper_id)
        add_node(
            paper_ref,
            "Paper",
            name=paper.get("title") or str(paper_id),
            year=paper.get("year"),
            doi=paper.get("doi"),
            source_url=paper.get("url"),
        )
        add_edge(report_ref, paper_ref, "REPORT_CONTAINS_PAPER")

    for claim in report.get("claims", []):
        claim_id = claim.get("claim_id") or claim.get("id")
        if not claim_id:
            continue
        claim_ref = _ref("claim", claim_id)
        add_node(
            claim_ref,
            "Claim",
            name=claim.get("text") or str(claim_id),
            claim_type=claim.get("claim_type"),
            validation_status=claim.get("validation_status"),
        )
        add_edge(report_ref, claim_ref, "REPORT_CONTAINS_CLAIM")
        supporting = {str(value) for value in claim.get("supporting_paper_ids", []) if value}
        for evidence_index, evidence in enumerate(claim.get("evidence", []), start=1):
            paper_id = evidence.get("paper_id")
            if paper_id:
                supporting.add(str(paper_id))
            evidence_id = evidence.get("evidence_id") or (
                "ev_"
                + content_hash(
                    {
                        "claim_id": claim_id,
                        "paper_id": paper_id,
                        "section": evidence.get("section"),
                        "quote": evidence.get("quote"),
                        "index": evidence_index,
                    }
                )[:24]
            )
            evidence_ref = _ref("evidence", evidence_id)
            add_node(
                evidence_ref,
                "Evidence",
                name=f"Evidence for {claim_id}",
                section=evidence.get("section"),
            )
            add_edge(claim_ref, evidence_ref, "CLAIM_SUPPORTED_BY")
            if paper_id:
                add_edge(evidence_ref, _ref("paper", paper_id), "EVIDENCE_FROM_PAPER")
        for paper_id in sorted(supporting):
            add_edge(claim_ref, _ref("paper", paper_id), "CLAIM_SUPPORTED_BY_PAPER")

    authoritative_gaps = gaps or list(report.get("potential_gaps", []))
    for gap in authoritative_gaps:
        gap_id = gap.get("gap_id") or gap.get("id")
        if not gap_id:
            continue
        gap_ref = _ref("gap", gap_id)
        add_node(
            gap_ref,
            "ResearchGap",
            name=(gap.get("scoped_statement") or gap.get("scope_statement") or gap.get("aspect") or str(gap_id)),
            gap_type=gap.get("gap_type"),
            status=gap.get("status"),
            verification_status=gap.get("verification_status"),
        )
        add_edge(report_ref, gap_ref, "REPORT_IDENTIFIES_GAP")
        for coverage in gap.get("coverage", []):
            if not isinstance(coverage, dict) or not coverage.get("paper_id"):
                continue
            add_edge(
                gap_ref,
                _ref("paper", coverage["paper_id"]),
                "GAP_COVERED_BY_PAPER",
                mentioned=coverage.get("mentioned"),
            )
        for paper_id in gap.get("counterevidence_paper_ids", []):
            if paper_id:
                add_edge(
                    gap_ref,
                    _ref("paper", paper_id),
                    "GAP_CONTRADICTED_BY_PAPER",
                )

    payload = {
        "schema_version": "core_graph_snapshot.v1",
        "project_id": project_id,
        "graph_version_id": graph_version_id,
        "corpus_hash": version.get("corpus_hash"),
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": [edges[key] for key in sorted(edges)],
    }
    return {**payload, "snapshot_hash": content_hash(payload)}


class CoreSandboxIntegrationService:
    def __init__(self, repository: CoreSandboxRepository) -> None:
        self._repository = repository

    def graph_snapshot(self, *, project_id: str, graph_version_id: str, actor_id: str) -> dict[str, Any]:
        self._require_membership(project_id=project_id, actor_id=actor_id)
        if graph_version_id == "current":
            project = self._repository.get_project(project_id)
            graph_version_id = str((project or {}).get("active_report_version_id") or "")
            if not graph_version_id:
                raise CoreSandboxIntegrationError(
                    "GRAPH_SNAPSHOT_NOT_FOUND",
                    "This project does not have an active report-backed graph version",
                    status_code=404,
                )
        version = self._repository.get_report_version(project_id, graph_version_id)
        if version is None:
            raise CoreSandboxIntegrationError(
                "GRAPH_SNAPSHOT_NOT_FOUND",
                "The requested report-backed graph version does not exist in this project",
                status_code=404,
            )
        return project_report_graph(
            project_id=project_id,
            version=version,
            gaps=self._repository.list_gaps(project_id, graph_version_id),
        )

    def adoption_is_current(
        self,
        *,
        project_id: str,
        actor_id: str,
        base_graph_version_id: str | None,
        source_type: str = "overlay_assessment",
    ) -> bool:
        if self._repository.membership(project_id, actor_id) is None:
            return False
        project = self._repository.get_project(project_id)
        if project is None:
            return False
        if source_type == "hypothesis" and base_graph_version_id is None:
            return True
        return bool(base_graph_version_id and project.get("active_report_version_id") == base_graph_version_id)

    def create_adoption_draft(
        self,
        *,
        project_id: str,
        actor_id: str,
        correlation_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_membership(project_id=project_id, actor_id=actor_id)
        source_bundle = payload.get("source_bundle")
        if not isinstance(source_bundle, dict):
            raise CoreSandboxIntegrationError(
                "INVALID_ADOPTION_BUNDLE", "Adoption source_bundle is required", status_code=422
            )
        source_hash = str(payload.get("source_hash") or "")
        if not source_hash or not hmac_compare(source_hash, content_hash(source_bundle)):
            raise CoreSandboxIntegrationError(
                "INVALID_ADOPTION_BUNDLE", "Adoption source hash does not match the immutable bundle", status_code=422
            )
        base_version = source_bundle.get("base_graph_version_id")
        if not self.adoption_is_current(
            project_id=project_id,
            actor_id=actor_id,
            base_graph_version_id=str(base_version) if base_version else None,
            source_type=str(payload.get("source_type") or ""),
        ):
            raise CoreSandboxIntegrationError(
                "ADOPTION_SOURCE_STALE",
                "The pinned report-backed graph version is no longer active",
            )
        proposal_id = str(payload.get("sandbox_proposal_id") or "")
        if not proposal_id:
            raise CoreSandboxIntegrationError(
                "INVALID_ADOPTION_BUNDLE", "sandbox_proposal_id is required", status_code=422
            )
        operation_refs = [
            value
            for operation in source_bundle.get("operations", [])
            if isinstance(operation, dict)
            for value in (operation.get("source_ref"), operation.get("target_ref"))
            if value
        ]
        action, created = self._repository.create_external_action(
            {
                "project_id": project_id,
                "conversation_id": None,
                "base_report_version_id": base_version,
                "action_type": ADOPTION_ACTION_TYPE,
                "parameters": {
                    "sandbox_proposal_id": proposal_id,
                    "source_type": payload.get("source_type"),
                    "source_id": payload.get("source_id"),
                    "source_hash": source_hash,
                    "source_bundle": source_bundle,
                    "sandbox_correlation_id": correlation_id,
                },
                "reason": str(payload.get("rationale") or "Sandbox adoption proposal"),
                "source_feedback_id": None,
                "external_source_system": SOURCE_SYSTEM,
                "external_source_id": proposal_id,
                "acceptance_criteria": [
                    "Core reviewer verifies the immutable Sandbox diff",
                    "Pinned report version remains active",
                    "No base graph mutation occurs during hand-off",
                ],
                "estimated_impact": {
                    "summary": "Review a Sandbox proposal without mutating the active report-backed graph.",
                    "affected_paper_ids": sorted(
                        {
                            str(value).removeprefix("paper:")
                            for value in operation_refs
                            if str(value).startswith("paper:")
                        }
                    ),
                    "affected_claim_ids": sorted(
                        {
                            str(value).removeprefix("claim:")
                            for value in operation_refs
                            if str(value).startswith("claim:")
                        }
                    ),
                    "affected_gap_ids": sorted(
                        {str(value).removeprefix("gap:") for value in operation_refs if str(value).startswith("gap:")}
                    ),
                    "may_change_corpus": False,
                    "requires_revalidation": True,
                    "expected_new_papers_min": 0,
                    "expected_new_papers_max": 0,
                    "cost_class": "low",
                },
                "proposed_by": actor_id,
            }
        )
        if created:
            self._repository.audit(
                project_id,
                actor_id,
                "sandbox.adoption_draft_created",
                "action_proposal",
                action["action_id"],
                str(base_version),
                metadata={
                    "sandbox_proposal_id": proposal_id,
                    "source_hash": source_hash,
                    "correlation_id": correlation_id,
                },
            )
        return action

    def _require_membership(self, *, project_id: str, actor_id: str) -> dict[str, Any]:
        membership = self._repository.membership(project_id, actor_id)
        if membership is None:
            raise CoreSandboxIntegrationError(
                "ENTITY_NOT_FOUND", "Project or graph version was not found", status_code=404
            )
        return membership


def hmac_compare(left: str, right: str) -> bool:
    """Constant-time comparison without exposing a signing primitive here."""

    import hmac

    return hmac.compare_digest(left, right)
