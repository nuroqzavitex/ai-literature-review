"""Release gates: an off sandbox is invisible to the main product and cannot leak data."""

from pathlib import Path
import sys

import pytest

from sandbox_service.domain.sessions import CreateSandboxSessionRequest
from sandbox_service.config import SandboxSettings
from sandbox_service.integration.gateway import SandboxGateway, SandboxGatewaySettings


class NeverCalledControlClient:
    def __init__(self) -> None:
        self.calls = 0

    async def create_session(self, **kwargs):
        self.calls += 1
        raise AssertionError("disabled sandbox must never call the control service")


class UnusedMapper:
    def verify(self, *args, **kwargs):
        raise AssertionError("manual disabled action must not map a context")


@pytest.mark.asyncio
async def test_release_gate_disabled_flags_preserve_core_and_prevent_outbound_work() -> None:
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    try:
        from src.config import Settings

        # Keep the release gate hermetic: a developer's local .env must not
        # change the asserted default configuration.
        settings = Settings(_env_file=None)
        assert settings.sandbox_enabled is False
        assert settings.sandbox_persistence_backend == "memory"
        assert settings.sandbox_database_url == ""
        sandbox_settings = SandboxSettings(
            SANDBOX_ENABLED="false",
            SANDBOX_HYPOTHESIS_ENABLED="false",
            SANDBOX_GRAPH_OVERLAY_ENABLED="false",
            SANDBOX_DATA_ANALYSIS_ENABLED="false",
            SANDBOX_AI_ENABLED="false",
        )
        assert all(not sandbox_settings.allows_mode(mode) for mode in ("hypothesis", "graph_overlay", "data_analysis"))
        # Verify V1/V2 registrations are untouched and the feature-gated BFF
        # router is safely registered for capability discovery.
        main_source = (root / "src" / "main.py").read_text(encoding="utf-8")
        assert "app.include_router(v2_router, prefix=\"/api/v1\")" in main_source
        assert "from src.api.routers.sandbox import router as sandbox_router" in main_source
        assert "app.include_router(sandbox_router, prefix=\"/api/v1\")" in main_source
        assert "sandbox_gateway" not in main_source

        client = NeverCalledControlClient()
        gateway = SandboxGateway(
            settings=SandboxGatewaySettings(), client=client, context_mapper=UnusedMapper()
        )
        outcome = await gateway.open_session(
            project_id="project-release", actor_id="actor-release", correlation_id="corr-release",
            request=CreateSandboxSessionRequest(mode="hypothesis", entrypoint="manual", title="No-op sandbox"),
        )
        assert outcome.status == "disabled"
        assert outcome.show_sandbox_action is False
        assert client.calls == 0
    finally:
        sys.path.remove(str(root))
