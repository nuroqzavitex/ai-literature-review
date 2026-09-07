import httpx
import pytest

from src.agents.research_sandbox.infrastructure.gateway import SandboxControlGateway, sandbox_gateway_settings
from src.api.routers.sandbox import _PROXY_RULES
from src.config import Settings
from src.main import app


def test_sandbox_settings_are_namespaced_and_disabled_by_default() -> None:
    # Inspect declared defaults instead of process environment: this regression
    # also runs inside the enabled local Compose stack.
    assert Settings.model_fields["sandbox_enabled"].default is False
    assert Settings.model_fields["sandbox_persistence_backend"].default == "memory"
    assert Settings.model_fields["sandbox_database_url"].default == ""
    assert Settings.model_fields["sandbox_object_storage_backend"].default == "local"

    # Representative Mindmap/Literature/RAG settings remain available with
    # their original defaults after the Sandbox settings are merged.
    assert Settings.model_fields["slide_image_generation_enabled"].default is True
    assert Settings.model_fields["database_url"].default == ("postgresql://postgres:postgres@localhost:5432/litreview")
    assert Settings.model_fields["qdrant_collection"].default == "litreview_papers"
    assert Settings.model_fields["paper_storage_dir"].default == "/tmp/litreview-papers"


def test_sandbox_bff_router_is_registered_with_core_routes() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/v1/reviews" in paths
    assert "/api/v1/projects" in paths
    assert "/api/v1/projects/{project_id}/sandbox/capabilities" in paths
    assert "/api/v1/projects/{project_id}/sandbox/open-session" in paths


def test_sandbox_bff_allows_state_restoration_reads() -> None:
    def allowed(path: str) -> bool:
        return any("GET" in rule.methods and rule.pattern.fullmatch(path) for rule in _PROXY_RULES)

    assert allowed("datasets/dataset-a/profiles")
    assert allowed("analysis-plans/plan-a/versions/1/runs")


def test_sandbox_bff_allows_retrying_a_run_interpretation() -> None:
    def allowed(path: str) -> bool:
        return any("POST" in rule.methods and rule.pattern.fullmatch(path) for rule in _PROXY_RULES)

    assert allowed("sandbox-runs/run-a/interpretation")


@pytest.mark.asyncio
async def test_sandbox_gateway_uses_long_read_timeout_only_for_ai_mutations() -> None:
    observed: list[tuple[str, float]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.url.path, request.extensions["timeout"]["read"]))
        return httpx.Response(200, json={"ok": True})

    settings = Settings(
        _env_file=None,
        sandbox_enabled=True,
        sandbox_ai_enabled=True,
        sandbox_control_url="http://sandbox-control:8080",
        sandbox_service_auth_key="s" * 32,
        sandbox_request_timeout_seconds=5,
        sandbox_ai_request_timeout_seconds=180,
    )
    gateway = SandboxControlGateway(
        settings=sandbox_gateway_settings(settings),
        transport=httpx.MockTransport(handler),
    )
    common = {
        "project_id": "project-a",
        "actor_id": "actor-a",
        "correlation_id": "correlation-a",
    }

    await gateway.request(
        method="POST",
        path="/api/v1/projects/project-a/analysis-plans/plan-a/versions/1/runs",
        **common,
    )
    await gateway.request(
        method="GET",
        path="/api/v1/projects/project-a/datasets",
        **common,
    )

    assert observed == [
        ("/api/v1/projects/project-a/analysis-plans/plan-a/versions/1/runs", 180),
        ("/api/v1/projects/project-a/datasets", 5),
    ]
