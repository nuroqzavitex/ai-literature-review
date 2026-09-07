from __future__ import annotations

from typing import Any

import pytest

from src.agents.research_sandbox.application.core_integration import (
    CoreSandboxIntegrationError,
    CoreSandboxIntegrationService,
    content_hash,
)


class CoreRepositoryFake:
    def __init__(self) -> None:
        self.project = {"project_id": "project-a", "active_report_version_id": "report-v1"}
        self.version = {
            "report_version_id": "report-v1",
            "version_number": 1,
            "corpus_hash": "corpus-hash",
            "report": {
                "papers": [{"paper_id": "paper-a", "title": "Paper A", "year": 2025}],
                "claims": [
                    {
                        "claim_id": "claim-a",
                        "text": "Method A improves the measured outcome.",
                        "evidence": [
                            {
                                "paper_id": "paper-a",
                                "section": "Results",
                                "quote": "raw evidence text must not cross the graph boundary",
                            }
                        ],
                    }
                ],
            },
        }
        self.actions: dict[str, dict[str, Any]] = {}
        self.audit_events: list[dict[str, Any]] = []

    def membership(self, project_id: str, actor_id: str) -> dict[str, Any] | None:
        return {"project_id": project_id, "actor_id": actor_id} if project_id == "project-a" else None

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self.project if project_id == "project-a" else None

    def get_report_version(self, project_id: str, version_id: str) -> dict[str, Any] | None:
        if project_id == "project-a" and version_id == "report-v1":
            return self.version
        return None

    def list_gaps(self, project_id: str, version_id: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "gap_id": "gap-a",
                "report_version_id": "report-v1",
                "scoped_statement": "A reviewed research gap",
                "status": "reviewer_approved",
                "coverage": [{"paper_id": "paper-a", "mentioned": False}],
            }
        ]

    def create_external_action(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        source_id = data["external_source_id"]
        if source_id in self.actions:
            return self.actions[source_id], False
        action = {"action_id": "act-sandbox-1", "status": "proposed", **data}
        self.actions[source_id] = action
        return action, True

    def audit(self, *args: Any, **kwargs: Any) -> None:
        self.audit_events.append({"args": args, "kwargs": kwargs})


def test_current_graph_alias_resolves_to_immutable_report_projection() -> None:
    repository = CoreRepositoryFake()
    snapshot = CoreSandboxIntegrationService(repository).graph_snapshot(
        project_id="project-a", graph_version_id="current", actor_id="actor-a"
    )

    assert snapshot["graph_version_id"] == "report-v1"
    assert snapshot["snapshot_hash"]
    assert {node["id"] for node in snapshot["nodes"]} >= {
        "report:report-v1",
        "paper:paper-a",
        "claim:claim-a",
        "gap:gap-a",
    }
    assert "raw evidence text" not in str(snapshot)


def test_adoption_creates_one_idempotent_core_draft_and_rejects_stale_bundle() -> None:
    repository = CoreRepositoryFake()
    service = CoreSandboxIntegrationService(repository)
    bundle = {
        "schema_version": "sandbox_adoption_bundle.v1",
        "source_type": "overlay_assessment",
        "source_id": "assessment-a",
        "base_graph_version_id": "report-v1",
        "operations": [{"source_ref": "paper:paper-a", "target_ref": "gap:gap-a"}],
    }
    payload = {
        "sandbox_proposal_id": "proposal-a",
        "source_type": "overlay_assessment",
        "source_id": "assessment-a",
        "rationale": "Reviewer approved this hypothetical relation.",
        "source_hash": content_hash(bundle),
        "source_bundle": bundle,
    }

    first = service.create_adoption_draft(
        project_id="project-a", actor_id="actor-a", correlation_id="corr-1", payload=payload
    )
    second = service.create_adoption_draft(
        project_id="project-a", actor_id="actor-a", correlation_id="corr-2", payload=payload
    )

    assert first["action_id"] == second["action_id"]
    assert first["action_type"] == "adopt_sandbox_proposal"
    assert first["estimated_impact"]["affected_paper_ids"] == ["paper-a"]
    assert len(repository.audit_events) == 1

    repository.project["active_report_version_id"] = "report-v2"
    with pytest.raises(CoreSandboxIntegrationError) as error:
        service.create_adoption_draft(
            project_id="project-a",
            actor_id="actor-a",
            correlation_id="corr-3",
            payload={**payload, "sandbox_proposal_id": "proposal-b"},
        )
    assert error.value.code == "ADOPTION_SOURCE_STALE"
