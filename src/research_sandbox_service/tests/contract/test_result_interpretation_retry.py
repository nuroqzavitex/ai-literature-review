from fastapi import FastAPI
from fastapi.testclient import TestClient

from sandbox_service.api.dependencies import TrustedActorContext
from sandbox_service.api.error_handlers import install_error_handlers
from sandbox_service.api.results import router as results_router
from sandbox_service.domain.results import AnalysisResultInterpretationRecord


class EnabledSettings:
    enabled = True
    data_analysis_enabled = True
    ai_enabled = True
    result_interpretation_enabled = True

    def allows_mode(self, mode: str) -> bool:
        return mode == "data_analysis"


class TrustedResolver:
    def resolve(self, *, request, project_id: str) -> TrustedActorContext:
        return TrustedActorContext(
            actor_id="actor-contract",
            project_id=project_id,
            correlation_id="correlation-contract",
        )


class InterpretationService:
    async def interpret_validated(
        self, *, project_id: str, run_id: str, correlation_id: str | None = None
    ):
        assert (project_id, run_id, correlation_id) == (
            "project-a",
            "run-a",
            "correlation-contract",
        )
        return (
            AnalysisResultInterpretationRecord(
                interpretation_id="interpretation-a",
                project_id=project_id,
                run_id=run_id,
                validation_id="validation-a",
                narrative=["The validated result supports the reported association."],
            ),
            [],
        )


def test_post_interpretation_generates_and_returns_the_durable_record() -> None:
    app = FastAPI()
    app.state.sandbox_settings = EnabledSettings()
    app.state.sandbox_actor_context_resolver = TrustedResolver()
    app.state.result_review_service = InterpretationService()
    app.include_router(results_router)
    install_error_handlers(app)

    response = TestClient(app).post(
        "/api/v1/projects/project-a/sandbox-runs/run-a/interpretation"
    )

    assert response.status_code == 200
    assert response.json()["interpretation_id"] == "interpretation-a"
    assert response.json()["run_id"] == "run-a"
