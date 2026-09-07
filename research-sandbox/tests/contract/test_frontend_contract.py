"""HTTP/OpenAPI release contract consumed by the Sandbox frontend."""

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sandbox_service.api.adoption import router as adoption_router
from sandbox_service.api.error_handlers import install_error_handlers
from sandbox_service.api.execution import router as execution_router
from sandbox_service.api.frontend import router as frontend_router
from sandbox_service.domain.adoption import AdoptionProposal, AdoptionProposalStatus
from sandbox_service.domain.execution import (
    AnalysisArtifact,
    AnalysisCodeStatus,
    AnalysisCodeVersion,
    SandboxRunStatus,
    SandboxRunStatusHistory,
)
from sandbox_service.domain.results import (
    AnalysisCitation,
    AnalysisResultInterpretationRecord,
    AnalysisResultValidation,
    InterpretationNumericClaim,
    ResultValidationStatus,
)
from sandbox_service.api.dependencies import TrustedActorContext
from sandbox_service.config import SandboxSettings
from sandbox_service.frontend_service import FrontendQueryService
from sandbox_service.main import create_app


class EnabledSettings:
    enabled = True
    hypothesis_enabled = True
    graph_overlay_enabled = True
    data_analysis_enabled = True
    ai_enabled = True
    graph_context_enabled = True
    result_interpretation_enabled = True
    allow_local_actor_headers = False

    def allows_mode(self, mode: str) -> bool:
        return self.enabled and {
            "hypothesis": self.hypothesis_enabled,
            "graph_overlay": self.graph_overlay_enabled,
            "data_analysis": self.data_analysis_enabled,
        }.get(mode, False)


class DisabledSettings(EnabledSettings):
    enabled = False


class TrustedResolver:
    def resolve(self, *, request, project_id: str) -> TrustedActorContext:
        return TrustedActorContext(
            actor_id="actor-contract",
            project_id=project_id,
            correlation_id="correlation-contract",
        )


class QueryRepository:
    def __init__(self, content: bytes) -> None:
        self.run = SimpleNamespace(
            project_id="project-a", run_id="run-a", code_version_id="code-version-a"
        )
        self.code = AnalysisCodeVersion(
            code_version_id="code-version-a",
            code_id="code-a",
            project_id="project-a",
            plan_id="plan-a",
            plan_version=1,
            source_code="from sandbox_sdk import load_dataset\ndf = load_dataset()\n",
            code_hash="code-hash",
            prompt_version="analysis.code_generation.v1",
            status=AnalysisCodeStatus.APPROVED,
        )
        self.artifact = AnalysisArtifact(
            artifact_id="artifact-a",
            project_id="project-a",
            run_id="run-a",
            artifact_type="table",
            filename="tables/summary.csv",
            content_hash=__import__("hashlib").sha256(content).hexdigest(),
            size_bytes=len(content),
            storage_key="private/project-a/run-a/summary.csv",
        )
        self.validation = AnalysisResultValidation(
            project_id="project-a",
            run_id="run-a",
            result_hash="result-hash",
            status=ResultValidationStatus.VALIDATED,
        )
        claim = InterpretationNumericClaim(
            statement="The score was 0.8.", value=0.8, locator="/metrics/0/value"
        )
        self.interpretation = AnalysisResultInterpretationRecord(
            project_id="project-a",
            run_id="run-a",
            validation_id=self.validation.validation_id,
            narrative=["The validated result supports the reported association."],
            numeric_claims=[claim],
            citation_ids=["citation-a"],
        )
        self.citation = AnalysisCitation(
            citation_id="citation-a",
            project_id="project-a",
            dataset_id="dataset-a",
            dataset_hash="dataset-hash",
            plan_id="plan-a",
            plan_version=1,
            run_id="run-a",
            artifact_id="artifact-result",
            artifact_type="result",
            locator="/metrics/0/value",
            value_hash="value-hash",
        )

    async def get_sandbox_run(self, *, project_id: str, run_id: str):
        return self.run if (project_id, run_id) == ("project-a", "run-a") else None

    async def list_artifacts(self, *, project_id: str, run_id: str):
        return [self.artifact] if await self.get_sandbox_run(project_id=project_id, run_id=run_id) else []

    async def list_sandbox_run_status_history(self, *, project_id: str, run_id: str):
        if not await self.get_sandbox_run(project_id=project_id, run_id=run_id):
            return []
        return [
            SandboxRunStatusHistory(
                run_id=run_id,
                project_id=project_id,
                to_status=SandboxRunStatus.QUEUED,
                changed_by="control-plane",
            )
        ]

    async def get_analysis_code(self, *, project_id: str, code_version_id: str):
        if project_id == "project-a" and code_version_id == self.code.code_version_id:
            return self.code
        return None

    async def get_result_validation(self, *, project_id: str, run_id: str):
        return self.validation if await self.get_sandbox_run(project_id=project_id, run_id=run_id) else None

    async def get_result_interpretation(self, *, project_id: str, run_id: str):
        return self.interpretation if await self.get_sandbox_run(project_id=project_id, run_id=run_id) else None

    async def list_analysis_citations(self, *, project_id: str, run_id: str):
        return [self.citation] if await self.get_sandbox_run(project_id=project_id, run_id=run_id) else []


class ObjectStore:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def get_bytes(self, *, key: str) -> bytes:
        return self.content


def contract_app(*, settings=None, resolver=True) -> FastAPI:
    content = b"metric,value\nscore,0.8\n"
    app = FastAPI()
    app.state.sandbox_settings = settings or EnabledSettings()
    if resolver:
        app.state.sandbox_actor_context_resolver = TrustedResolver()
    app.state.frontend_query_service = FrontendQueryService(
        repository=QueryRepository(content), object_store=ObjectStore(content)
    )
    app.include_router(execution_router)
    app.include_router(frontend_router)
    install_error_handlers(app)
    return app


def test_capabilities_are_public_and_kill_switch_wins() -> None:
    client = TestClient(contract_app(settings=DisabledSettings(), resolver=False))
    response = client.get("/api/v1/sandbox/capabilities")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["modes"] == {
        "hypothesis": False,
        "graph_overlay": False,
        "data_analysis": False,
    }
    blocked = client.get("/api/v1/projects/project-a/sandbox-runs/run-a/artifacts")
    assert blocked.status_code == 404
    assert blocked.json()["detail"]["error_code"] == "SANDBOX_FEATURE_DISABLED"


def test_browser_routes_require_a_trusted_project_scoped_actor() -> None:
    client = TestClient(contract_app(resolver=False))
    response = client.get("/api/v1/projects/project-a/sandbox-runs/run-a/artifacts")
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "SANDBOX_AUTHENTICATION_REQUIRED"


def test_artifact_contract_hides_storage_key_and_download_is_hash_verified() -> None:
    client = TestClient(contract_app())
    listed = client.get("/api/v1/projects/project-a/sandbox-runs/run-a/artifacts")
    assert listed.status_code == 200
    artifact = listed.json()[0]
    assert "storage_key" not in artifact
    assert artifact["download_url"].endswith("/artifacts/artifact-a/content")

    downloaded = client.get(artifact["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.content == b"metric,value\nscore,0.8\n"
    assert downloaded.headers["content-disposition"] == 'attachment; filename="summary.csv"'
    assert downloaded.headers["x-content-type-options"] == "nosniff"


def test_validation_interpretation_citations_and_history_are_project_scoped() -> None:
    client = TestClient(contract_app())
    base = "/api/v1/projects/project-a/sandbox-runs/run-a"
    assert client.get(f"{base}/validation").json()["status"] == "validated"
    assert client.get(f"{base}/interpretation").json()["citation_ids"] == ["citation-a"]
    assert client.get(f"{base}/citations").json()[0]["locator"] == "/metrics/0/value"
    assert client.get(f"{base}/status-history").json()[0]["to_status"] == "queued"

    foreign = client.get("/api/v1/projects/project-b/sandbox-runs/run-a/validation")
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["error_code"] == "SANDBOX_RUN_NOT_FOUND"


def test_generated_code_is_exact_and_project_scoped() -> None:
    client = TestClient(contract_app())
    response = client.get("/api/v1/projects/project-a/sandbox-runs/run-a/code")
    assert response.status_code == 200
    assert response.json()["source_code"] == (
        "from sandbox_sdk import load_dataset\ndf = load_dataset()\n"
    )
    assert response.json()["run_id"] == "run-a"
    assert "project_id" not in response.json()

    foreign = client.get("/api/v1/projects/project-b/sandbox-runs/run-a/code")
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["error_code"] == "SANDBOX_RUN_NOT_FOUND"


def test_openapi_exposes_frontend_reads_without_worker_or_storage_internals() -> None:
    schema = contract_app().openapi()
    paths = schema["paths"]
    assert "/api/v1/sandbox/capabilities" in paths
    assert "/api/v1/projects/{project_id}/datasets/{dataset_id}/analysis-questions" in paths
    assert "/api/v1/projects/{project_id}/analysis-plans/{plan_id}/versions" in paths
    assert "/api/v1/projects/{project_id}/sandbox-runs/{run_id}/validation" in paths
    assert "/api/v1/projects/{project_id}/sandbox-runs/{run_id}/interpretation" in paths
    assert "/api/v1/projects/{project_id}/sandbox-runs/{run_id}/citations" in paths
    assert "/api/v1/projects/{project_id}/sandbox-runs/{run_id}/code" in paths
    assert "manifest" not in schema["components"]["schemas"]["PublicSandboxRun"]["properties"]
    assert "storage_key" not in schema["components"]["schemas"]["AnalysisArtifactSummary"]["properties"]


class AdoptionService:
    def __init__(self, proposal: AdoptionProposal) -> None:
        self.proposal = proposal

    async def get(self, *, project_id: str, proposal_id: str) -> AdoptionProposal:
        assert project_id == self.proposal.project_id
        assert proposal_id == self.proposal.proposal_id
        return self.proposal

    async def handoff_bundle(self, *, project_id: str, proposal: AdoptionProposal) -> dict:
        assert project_id == proposal.project_id
        return {
            "schema_version": "sandbox_adoption_bundle.v1",
            "source_type": proposal.source_type.value,
            "source_id": proposal.source_id,
            "base_graph_version_id": None,
        }


class AdoptionBridge:
    def __init__(self) -> None:
        self.calls = 0
        self.results = {}

    async def hand_off(self, **kwargs) -> str:
        key = (kwargs["project_id"], kwargs["idempotency_key"])
        if key not in self.results:
            self.calls += 1
            self.results[key] = "core-draft-a"
        return self.results[key]


def test_adoption_handoff_has_idempotent_frontend_response() -> None:
    proposal = AdoptionProposal(
        proposal_id="proposal-a",
        project_id="project-a",
        session_id="session-a",
        source_type="hypothesis",
        source_id="hypothesis-a",
        rationale="Reviewed finding",
        status=AdoptionProposalStatus.APPROVED,
        requested_by="actor-a",
    )
    bridge = AdoptionBridge()
    app = FastAPI()
    app.state.sandbox_settings = EnabledSettings()
    app.state.sandbox_actor_context_resolver = TrustedResolver()
    app.state.adoption_proposal_service = AdoptionService(proposal)
    app.state.adoption_proposal_bridge = bridge
    app.include_router(adoption_router)
    install_error_handlers(app)
    client = TestClient(app)
    url = "/api/v1/projects/project-a/sandbox-adoption-proposals/proposal-a/handoff"
    first = client.post(url, headers={"Idempotency-Key": "handoff-a"})
    second = client.post(url, headers={"Idempotency-Key": "handoff-a"})
    assert first.status_code == second.status_code == 200
    assert first.json() == {
        "proposal_id": "proposal-a",
        "core_draft_id": "core-draft-a",
        "status": "draft_created",
    }
    assert bridge.calls == 1


def test_request_validation_uses_the_same_error_envelope() -> None:
    client = TestClient(contract_app())
    response = client.get(
        "/api/v1/projects/project-a/analysis-plans/plan-a/versions/not-an-int/decisions"
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "REQUEST_VALIDATION_FAILED"
    assert response.json()["detail"]["correlation_id"] == "correlation-contract"


def test_session_close_discard_and_status_history_are_idempotent() -> None:
    app = create_app(
        settings=SandboxSettings(
            SANDBOX_ENABLED=True,
            SANDBOX_HYPOTHESIS_ENABLED=True,
        ),
        actor_context_resolver=TrustedResolver(),
    )
    client = TestClient(app)
    collection = "/api/v1/projects/project-a/sandbox-sessions"
    created = client.post(
        collection,
        json={"mode": "hypothesis", "entrypoint": "manual", "title": "Closable"},
    ).json()
    session_url = f"{collection}/{created['session_id']}"
    first = client.post(f"{session_url}/close")
    repeated = client.post(f"{session_url}/close")
    assert first.status_code == repeated.status_code == 200
    assert first.json()["status"] == repeated.json()["status"] == "completed"
    history = client.get(f"{session_url}/status-history").json()
    assert [item["to_status"] for item in history] == ["draft", "completed"]
    assert client.post(f"{session_url}/discard").status_code == 409

    discarded = client.post(
        collection,
        json={"mode": "hypothesis", "entrypoint": "manual", "title": "Discardable"},
    ).json()
    discard_url = f"{collection}/{discarded['session_id']}/discard"
    assert client.post(discard_url).json()["status"] == "discarded"
    assert client.post(discard_url).json()["status"] == "discarded"
