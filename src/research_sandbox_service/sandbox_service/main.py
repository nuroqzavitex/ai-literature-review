"""Standalone FastAPI application factory for the sandbox control plane."""

from pathlib import Path
import inspect
import importlib
from typing import Any, Awaitable, Callable, Mapping

from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse

from sandbox_service.adoption import AdoptionProposalService
from sandbox_service.analysis_service import AnalysisPlanService
from sandbox_service.analysis_graph import AnalysisGraph
from sandbox_service.api.adoption import router as adoption_router
from sandbox_service.api.analysis_plans import router as analysis_plans_router
from sandbox_service.api.datasets import router as datasets_router
from sandbox_service.api.execution import router as execution_router
from sandbox_service.api.frontend import router as frontend_router
from sandbox_service.api.results import router as results_router
from sandbox_service.api.graph_overlays import router as graph_overlays_router
from sandbox_service.api.gateway import create_gateway_router
from sandbox_service.api.hypotheses import router as hypotheses_router
from sandbox_service.api.sessions import router as sessions_router
from sandbox_service.api.error_handlers import install_error_handlers
from sandbox_service.api.dependencies import SignedServiceActorContextResolver
from sandbox_service.api.service_auth_middleware import SignedServiceAuthMiddleware
from sandbox_service.config import SandboxSettings
from sandbox_service.frontend_service import FrontendQueryService
from sandbox_service.graph_overlay import GraphOverlaySandboxService
from sandbox_service.hypothesis_graph import HypothesisSandboxGraph
from sandbox_service.repositories import InMemorySandboxSessionRepository, PostgresSandboxRepository
from sandbox_service.dataset_service import DatasetService
from sandbox_service.code_generation_service import CodeGenerationService
from sandbox_service.execution.manifest import ManifestSigner
from sandbox_service.execution.runner import EphemeralRunner, ExecutionResult
from sandbox_service.execution_service import ExecutionService
from sandbox_service.result_service import ResultReviewService
from sandbox_service.session_service import SandboxSessionService
from sandbox_service.storage import LocalObjectStore, S3ObjectStore
from sandbox_service.integration.auth import (
    ContextSnapshotSigner,
    InMemoryReplayStore,
    SignedServiceAuth,
)
from sandbox_service.integration.context_mapping import ResearchContextMapper
from sandbox_service.integration.postgres_replay import PostgresReplayStore
from sandbox_service.observability import SandboxMetrics


class _UnavailableProjectAIClient:
    async def invoke_structured(self, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("ProjectAIClient adapter is not configured")


class _UnavailableGraphSnapshotReader:
    async def read_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("GraphSnapshotReader adapter is not configured")


class _UnavailableRuntimeLauncher:
    async def run(self, **kwargs: Any) -> ExecutionResult:
        raise RuntimeError("Ephemeral runtime launcher is not configured")


def _load_adapter(factory_path: str | None, *, setting_name: str) -> Any | None:
    """Load a deployment adapter without silently falling back to a fake."""

    if not factory_path:
        return None
    if ":" not in factory_path:
        raise RuntimeError(f"{setting_name} must use module:function syntax")
    module_name, function_name = factory_path.split(":", 1)
    factory = getattr(importlib.import_module(module_name), function_name, None)
    if not callable(factory):
        raise RuntimeError(f"{setting_name} does not resolve to a callable")
    adapter = factory()
    if inspect.isawaitable(adapter):
        raise RuntimeError(f"{setting_name} factory must be synchronous during app startup")
    return adapter


def _verification_keys(
    previous_key_id: str | None, previous_key: Any | None
) -> dict[str, bytes]:
    if previous_key_id is None or previous_key is None:
        return {}
    return {previous_key_id: previous_key.get_secret_value().encode("utf-8")}


def create_app(
    service: SandboxSessionService | None = None,
    *,
    hypothesis_graph: HypothesisSandboxGraph | None = None,
    overlay_service: GraphOverlaySandboxService | None = None,
    adoption_service: AdoptionProposalService | None = None,
    dataset_service: DatasetService | None = None,
    analysis_plan_service: AnalysisPlanService | None = None,
    execution_service: ExecutionService | None = None,
    result_review_service: ResultReviewService | None = None,
    gateway_service_auth: SignedServiceAuth | None = None,
    gateway_context_mapper: ResearchContextMapper | None = None,
    metrics: SandboxMetrics | None = None,
    readiness_checks: Mapping[str, Callable[[], bool | Awaitable[bool]]] | None = None,
    settings: SandboxSettings | None = None,
    repository: Any | None = None,
    object_store: Any | None = None,
    project_ai_client: Any | None = None,
    graph_snapshot_reader: Any | None = None,
    actor_context_resolver: Any | None = None,
    adoption_bridge: Any | None = None,
) -> FastAPI:
    configured = settings or SandboxSettings()
    actor_context_was_injected = actor_context_resolver is not None
    project_ai_client = project_ai_client or _load_adapter(
        configured.project_ai_factory,
        setting_name="SANDBOX_PROJECT_AI_FACTORY",
    )
    graph_snapshot_reader = graph_snapshot_reader or _load_adapter(
        configured.graph_snapshot_reader_factory,
        setting_name="SANDBOX_GRAPH_SNAPSHOT_READER_FACTORY",
    )
    adoption_bridge = adoption_bridge or _load_adapter(
        configured.adoption_bridge_factory,
        setting_name="SANDBOX_ADOPTION_BRIDGE_FACTORY",
    )

    if gateway_service_auth is None and configured.enabled and configured.service_auth_key:
        replay_store = (
            PostgresReplayStore(str(configured.database_url))
            if configured.persistence_backend == "postgres" and configured.database_url
            else InMemoryReplayStore()
        )
        gateway_service_auth = SignedServiceAuth(
            signing_key=configured.service_auth_key.get_secret_value().encode("utf-8"),
            key_id=configured.service_auth_key_id,
            verification_keys=_verification_keys(
                configured.service_auth_previous_key_id,
                configured.service_auth_previous_key,
            ),
            replay_store=replay_store,
        )
    if gateway_context_mapper is None and configured.enabled and configured.context_signing_key:
        gateway_context_mapper = ResearchContextMapper(
            snapshot_signer=ContextSnapshotSigner(
                signing_key=configured.context_signing_key.get_secret_value().encode("utf-8"),
                key_id=configured.context_signing_key_id,
                verification_keys=_verification_keys(
                    configured.context_signing_previous_key_id,
                    configured.context_signing_previous_key,
                ),
            )
        )
    if actor_context_resolver is None and gateway_service_auth is not None:
        actor_context_resolver = SignedServiceActorContextResolver(gateway_service_auth)
    if configured.enabled and configured.ai_enabled and project_ai_client is None:
        raise RuntimeError(
            "SANDBOX_AI_ENABLED requires an injected ProjectAIClient adapter"
        )
    if (
        configured.allows_mode("graph_overlay")
        and graph_snapshot_reader is None
        and overlay_service is None
    ):
        raise RuntimeError(
            "graph-overlay mode requires an injected GraphSnapshotReader adapter"
        )
    if (
        configured.environment == "production"
        and gateway_service_auth is not None
        and isinstance(getattr(gateway_service_auth, "_replay_store", None), InMemoryReplayStore)
    ):
        raise RuntimeError(
            "production signed service auth requires a shared atomic ReplayStore"
        )

    app = FastAPI(title="Research Experiment Sandbox", version="1.0.0")
    if (
        gateway_service_auth is not None
        and not configured.allow_local_actor_headers
        and not actor_context_was_injected
    ):
        app.add_middleware(
            SignedServiceAuthMiddleware,
            service_auth=gateway_service_auth,
        )
    install_error_handlers(app)
    app.state.sandbox_settings = configured
    app.state.sandbox_actor_context_resolver = actor_context_resolver
    app.state.adoption_proposal_bridge = adoption_bridge
    app.state.sandbox_metrics = metrics or SandboxMetrics()
    if repository is None:
        if configured.persistence_backend == "postgres":
            assert configured.database_url is not None
            repository = PostgresSandboxRepository(
                str(configured.database_url),
                pool_size=configured.database_pool_size,
                max_overflow=configured.database_max_overflow,
                pool_timeout_seconds=configured.database_pool_timeout_seconds,
            )
        else:
            repository = InMemorySandboxSessionRepository()

    if object_store is None:
        if configured.object_storage_backend == "s3":
            object_store = S3ObjectStore(
                bucket=configured.object_storage_bucket or "",
                endpoint_url=configured.object_storage_endpoint,
                region_name=configured.object_storage_region,
                access_key_id=(
                    configured.object_storage_access_key.get_secret_value()
                    if configured.object_storage_access_key
                    else None
                ),
                secret_access_key=(
                    configured.object_storage_secret_key.get_secret_value()
                    if configured.object_storage_secret_key
                    else None
                ),
                server_side_encryption=configured.object_storage_server_side_encryption,
            )
        else:
            storage_root = configured.local_storage_path
            if not storage_root.is_absolute():
                storage_root = Path(__file__).resolve().parents[1] / storage_root
            object_store = LocalObjectStore(storage_root)

    effective_readiness = dict(readiness_checks or {})
    if isinstance(repository, PostgresSandboxRepository):
        async def database_ready() -> bool:
            await repository.ping()
            return True

        effective_readiness.setdefault("database", database_ready)
    storage_healthcheck = getattr(object_store, "healthcheck", None)
    if storage_healthcheck is not None:
        async def object_storage_ready() -> bool:
            await storage_healthcheck()
            return True

        effective_readiness.setdefault("object_storage", object_storage_ready)
    app.state.sandbox_readiness_checks = effective_readiness
    app.state.sandbox_repository = repository
    app.state.sandbox_object_store = object_store
    app.state.sandbox_session_service = service or SandboxSessionService(repository=repository)
    # Explicit production adapters are injected by the S7 gateway; local defaults
    # deliberately fail closed for AI/graph calls instead of touching the main backend.
    ai_client = project_ai_client or _UnavailableProjectAIClient()
    graph_reader = graph_snapshot_reader or _UnavailableGraphSnapshotReader()
    app.state.hypothesis_sandbox_graph = hypothesis_graph or HypothesisSandboxGraph(
        repository=repository, ai_client=ai_client
    )
    app.state.graph_overlay_service = overlay_service or GraphOverlaySandboxService(
        repository=repository, graph_reader=graph_reader
    )
    app.state.adoption_proposal_service = adoption_service or AdoptionProposalService(
        repository=repository
    )
    app.state.dataset_service = dataset_service or DatasetService(repository=repository, object_store=object_store)
    app.state.analysis_plan_service = analysis_plan_service or AnalysisPlanService(
        repository=repository, ai_client=ai_client
    )
    code_generation = CodeGenerationService(
        repository=repository, ai_client=ai_client
    )
    app.state.execution_service = execution_service or ExecutionService(
        repository=repository,
        code_generation=code_generation,
        manifest_signer=ManifestSigner(
            signing_key=configured.manifest_signing_key.get_secret_value().encode("utf-8")
        ),
        image_digest=configured.runtime_image_digest,
        package_manifest_hash=configured.package_manifest_hash,
    )
    app.state.result_review_service = result_review_service or ResultReviewService(
        repository=repository,
        object_store=object_store,
        ai_client=ai_client if configured.result_interpretation_enabled else None,
    )
    app.state.frontend_query_service = FrontendQueryService(
        repository=repository, object_store=object_store
    )
    app.state.analysis_graph = AnalysisGraph(execution_service=app.state.execution_service)
    # No background worker is started from FastAPI. Deployment wires a dedicated worker process.
    app.state.ephemeral_runner = EphemeralRunner(
        workspace_root=Path(__file__).resolve().parents[1] / ".sandbox-workspaces",
        launcher=_UnavailableRuntimeLauncher(),
    )
    app.include_router(sessions_router)
    app.include_router(hypotheses_router)
    app.include_router(graph_overlays_router)
    app.include_router(adoption_router)
    app.include_router(datasets_router)
    app.include_router(analysis_plans_router)
    app.include_router(execution_router)
    app.include_router(results_router)
    app.include_router(frontend_router)
    if gateway_service_auth is not None and gateway_context_mapper is not None:
        app.include_router(create_gateway_router(
            service_auth=gateway_service_auth,
            context_mapper=gateway_context_mapper,
        ))

    @app.get("/healthz", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"], response_model=None)
    async def ready() -> Response:
        dependencies: dict[str, str] = {}
        for name, check in app.state.sandbox_readiness_checks.items():
            try:
                outcome = check()
                available = bool(await outcome) if inspect.isawaitable(outcome) else bool(outcome)
            except Exception:
                available = False
            dependencies[name] = "ready" if available else "not_ready"
        is_ready = all(value == "ready" for value in dependencies.values())
        payload: dict[str, object] = {
            "status": "ready" if is_ready else "not_ready",
            "dependencies": dependencies,
        }
        return JSONResponse(
            payload,
            status_code=(
                status.HTTP_200_OK
                if is_ready
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
        )

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return Response(
            app.state.sandbox_metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4",
        )

    if isinstance(repository, PostgresSandboxRepository):
        @app.on_event("shutdown")
        async def dispose_database_pool() -> None:
            await repository.dispose()

    return app


app = create_app()
