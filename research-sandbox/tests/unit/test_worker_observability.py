import asyncio
import json
import logging

import pytest
from fastapi.testclient import TestClient

from sandbox_service.code_generation_service import CodeGenerationService
from sandbox_service.domain.errors import OutputValidationFailed
from sandbox_service.domain.execution import CreateSandboxRunRequest, SandboxRunStatus
from sandbox_service.domain.results import ResultValidationStatus
from sandbox_service.execution.manifest import ManifestSigner
from sandbox_service.execution.runner import EphemeralRunner, ExecutionResult
from sandbox_service.execution_service import ExecutionService
from sandbox_service.main import create_app
from sandbox_service.observability import (
    SandboxMetrics,
    StructuredEventLogger,
    WorkerProbeServer,
    WorkerProbeState,
)
from sandbox_service.worker import DurableExecutionWorker
from sandbox_service.worker.main import build_application_from_environment
from tests.fakes import FakeProjectAIClient
from tests.unit.test_execution import (
    VALID_CODE,
    SuccessfulLauncher,
    approve_plan,
    approved_execution_context,
)


class FailingInterpretationPipeline:
    async def validate_run(self, *, project_id: str, run_id: str):
        return type("Validation", (), {"status": ResultValidationStatus.VALIDATED})()

    async def interpret_validated(self, *, project_id: str, run_id: str):
        raise OutputValidationFailed("Numeric claim locator does not resolve to a number")


class BlockingLauncher:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancel_calls = 0

    async def run(self, **kwargs) -> ExecutionResult:
        self.started.set()
        await self.release.wait()
        return ExecutionResult(exit_code=0)

    async def cancel(self, *, run_id: str) -> None:
        self.cancel_calls += 1
        self.release.set()


@pytest.mark.asyncio
async def test_worker_renews_lease_and_cancels_active_runtime(tmp_path) -> None:
    repository, store, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    signer = ManifestSigner(signing_key=b"heartbeat-manifest-signing-key-32-bytes")
    execution = ExecutionService(
        repository=repository,
        code_generation=CodeGenerationService(
            repository=repository,
            ai_client=FakeProjectAIClient(responses=[{"source_code": VALID_CODE}]),
        ),
        manifest_signer=signer,
        image_digest="sandbox-runtime@sha256:" + "1" * 64,
        package_manifest_hash="2" * 64,
    )
    run = await execution.queue_run(
        project_id="project-a",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        actor_id="user-a",
        idempotency_key="heartbeat-run",
        request=CreateSandboxRunRequest(),
    )
    launcher = BlockingLauncher()
    metrics = SandboxMetrics()
    worker = DurableExecutionWorker(
        repository=repository,
        object_store=store,
        runner=EphemeralRunner(workspace_root=tmp_path / "workspaces", launcher=launcher),
        manifest_signer=signer,
        worker_id="worker-heartbeat",
        lease_seconds=1,
        heartbeat_interval_seconds=0.02,
        metrics=metrics,
    )

    task = asyncio.create_task(worker.process_next())
    await asyncio.wait_for(launcher.started.wait(), timeout=1)
    claimed = await repository.get_sandbox_run(project_id="project-a", run_id=run.run_id)
    initial_expiry = claimed.lease_expires_at
    await asyncio.sleep(0.06)
    renewed = await repository.get_sandbox_run(project_id="project-a", run_id=run.run_id)
    assert renewed.lease_expires_at > initial_expiry

    cancelled = await execution.cancel_run(
        project_id="project-a", run_id=run.run_id, actor_id="user-a"
    )
    outcome = await asyncio.wait_for(task, timeout=1)

    assert cancelled.status is SandboxRunStatus.CANCELLED
    assert outcome.status is SandboxRunStatus.CANCELLED
    assert launcher.cancel_calls >= 1
    snapshot = metrics.snapshot()
    assert snapshot["counters"]['sandbox_worker_lease_renew_total{result="renewed"}'] >= 1
    assert snapshot["counters"]['sandbox_worker_runtime_cancel_total{reason="user_cancelled"}'] == 1


@pytest.mark.asyncio
async def test_worker_logs_interpretation_failure_type_without_payload(
    tmp_path, caplog
) -> None:
    repository, store, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    signer = ManifestSigner(signing_key=b"interpretation-log-signing-key-32b")
    execution = ExecutionService(
        repository=repository,
        code_generation=CodeGenerationService(
            repository=repository,
            ai_client=FakeProjectAIClient(responses=[{"source_code": VALID_CODE}]),
        ),
        manifest_signer=signer,
        image_digest="sandbox-runtime@sha256:" + "1" * 64,
        package_manifest_hash="2" * 64,
    )
    await execution.queue_run(
        project_id="project-a",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        actor_id="user-a",
        idempotency_key="interpretation-log-run",
        request=CreateSandboxRunRequest(),
    )
    caplog.set_level(logging.INFO, logger="sandbox.worker")
    worker = DurableExecutionWorker(
        repository=repository,
        object_store=store,
        runner=EphemeralRunner(
            workspace_root=tmp_path / "workspaces", launcher=SuccessfulLauncher()
        ),
        manifest_signer=signer,
        worker_id="worker-interpretation-log",
        result_pipeline=FailingInterpretationPipeline(),
    )

    await worker.process_next()

    failure_logs = [
        record.message
        for record in caplog.records
        if "sandbox_result_interpretation_failed" in record.message
    ]
    assert len(failure_logs) == 1
    assert '"error_code":"OutputValidationFailed"' in failure_logs[0]
    assert "Numeric claim locator" not in failure_logs[0]


def test_structured_logs_metrics_and_probes_never_include_unapproved_payload(caplog) -> None:
    metrics = SandboxMetrics()
    metrics.increment("sandbox_run_terminal_total", labels={"status": "failed"})
    metrics.observe("sandbox_worker_run_duration_seconds", 0.25)
    state = WorkerProbeState(ready=False)
    probes = WorkerProbeServer(state=state, metrics=metrics, host="127.0.0.1", port=0)

    status, _, body = probes.response_for("/readyz")
    assert status == 503 and json.loads(body)["status"] == "not_ready"
    state.ready = True
    assert probes.response_for("/readyz")[0] == 200
    rendered_metrics = probes.response_for("/metrics")[2].decode("utf-8")
    assert 'sandbox_run_terminal_total{status="failed"} 1' in rendered_metrics
    assert "sandbox_worker_run_duration_seconds_count 1" in rendered_metrics

    caplog.set_level(logging.INFO, logger="sandbox.worker")
    StructuredEventLogger().emit(
        "runtime_failed",
        run_id="run-1",
        reason="token=top-secret",
        raw_dataset="private,value\n1,2",
    )
    logged = caplog.records[-1].message
    assert "top-secret" not in logged and "private,value" not in logged
    assert "<redacted>" in logged


def test_control_service_readiness_and_metrics_are_dependency_aware() -> None:
    metrics = SandboxMetrics()
    metrics.increment("sandbox_http_requests_total")
    app = create_app(
        metrics=metrics,
        readiness_checks={"database": lambda: False, "object_store": lambda: True},
    )
    client = TestClient(app)

    readiness = client.get("/readyz")
    exposed = client.get("/metrics")

    assert readiness.status_code == 503
    assert readiness.json()["dependencies"] == {
        "database": "not_ready",
        "object_store": "ready",
    }
    assert "sandbox_http_requests_total 1" in exposed.text


@pytest.mark.asyncio
async def test_worker_entrypoint_refuses_implicit_in_memory_fallback(monkeypatch) -> None:
    monkeypatch.delenv("SANDBOX_WORKER_FACTORY", raising=False)
    with pytest.raises(RuntimeError, match="SANDBOX_WORKER_FACTORY is required"):
        await build_application_from_environment()
