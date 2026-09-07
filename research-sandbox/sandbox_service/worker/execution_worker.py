"""Lease one queued run, validate its sealed manifest, then delegate to the runner."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import logging
import time
from typing import Protocol

from sandbox_service.code_policy import CodePolicyChecker, CodePolicyViolation
from sandbox_service.domain.execution import AnalysisArtifact, AnalysisCodeVersion, SandboxRun, SandboxRunStatus
from sandbox_service.execution.manifest import ManifestSigner, ManifestVerificationError
from sandbox_service.execution.docker_launcher import RuntimeUnavailable
from sandbox_service.execution.runner import (
    ArtifactPolicyViolation,
    EphemeralRunner,
    ExecutionRequest,
    ExecutionResult,
    RuntimeSecuritySpec,
)
from sandbox_service.domain.results import ResultValidationStatus
from sandbox_service.observability import (
    SandboxMetrics,
    StructuredEventLogger,
    WorkerProbeState,
)


class WorkerRepository(Protocol):
    async def claim_sandbox_run(self, *, worker_id: str, now: datetime, lease_seconds: int) -> SandboxRun | None: ...

    async def renew_sandbox_run_lease(
        self, *, run_id: str, worker_id: str, now: datetime, lease_seconds: int
    ) -> bool: ...

    async def get_sandbox_run(self, *, project_id: str, run_id: str) -> SandboxRun | None: ...

    async def update_sandbox_run(self, run: SandboxRun, *, changed_by: str, reason: str | None = None) -> SandboxRun: ...

    async def consume_manifest_nonce(self, *, nonce: str, run_id: str) -> bool: ...

    async def get_analysis_code(self, *, project_id: str, code_version_id: str) -> AnalysisCodeVersion | None: ...

    async def get_dataset(self, *, project_id: str, dataset_id: str, include_deleted: bool = False): ...

    async def save_artifact(self, artifact: AnalysisArtifact) -> AnalysisArtifact: ...


class WorkerObjectStore(Protocol):
    async def get_bytes(self, *, key: str) -> bytes: ...

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str: ...


class ResultPipeline(Protocol):
    async def validate_run(self, *, project_id: str, run_id: str): ...
    async def interpret_validated(self, *, project_id: str, run_id: str, correlation_id: str | None = None): ...


class DurableExecutionWorker:
    def __init__(
        self,
        *,
        repository: WorkerRepository,
        object_store: WorkerObjectStore,
        runner: EphemeralRunner,
        manifest_signer: ManifestSigner,
        worker_id: str,
        lease_seconds: int = 60,
        heartbeat_interval_seconds: float | None = None,
        policy_checker: CodePolicyChecker | None = None,
        result_pipeline: ResultPipeline | None = None,
        metrics: SandboxMetrics | None = None,
        event_logger: StructuredEventLogger | None = None,
        probe_state: WorkerProbeState | None = None,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._repository = repository
        self._object_store = object_store
        self._runner = runner
        self._signer = manifest_signer
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._heartbeat_interval = heartbeat_interval_seconds or max(
            0.05, min(5.0, lease_seconds / 3)
        )
        if self._heartbeat_interval >= lease_seconds:
            raise ValueError("heartbeat interval must be shorter than the lease")
        self._policy = policy_checker or CodePolicyChecker()
        self._result_pipeline = result_pipeline
        self.metrics = metrics or SandboxMetrics()
        self.events = event_logger or StructuredEventLogger()
        self.probe_state = probe_state
        self._active_run_id: str | None = None

    @property
    def active_run_id(self) -> str | None:
        return self._active_run_id

    async def ready(self) -> bool:
        for dependency in (self._repository, self._object_store):
            readiness = getattr(dependency, "ready", None)
            if readiness is not None and not await readiness():
                return False
        return await self._runner.ready()

    async def process_next(self, *, now: datetime | None = None) -> SandboxRun | None:
        started = time.monotonic()
        current_time = now or datetime.now(timezone.utc)
        run = await self._repository.claim_sandbox_run(
            worker_id=self._worker_id, now=current_time, lease_seconds=self._lease_seconds
        )
        if run is None:
            self.metrics.increment("sandbox_worker_poll_total", labels={"result": "empty"})
            return None
        self._active_run_id = run.run_id
        if self.probe_state is not None:
            self.probe_state.active_run_id = run.run_id
        self.metrics.increment("sandbox_worker_poll_total", labels={"result": "claimed"})
        self.metrics.set_gauge(
            "sandbox_worker_active_runs", 1, labels={"worker_id": self._worker_id}
        )
        self.events.emit(
            "sandbox_run_claimed",
            run_id=run.run_id,
            project_id=run.project_id,
            worker_id=self._worker_id,
            lease_owner=run.lease_owner,
            status=run.status.value,
        )
        try:
            self._signer.verify(run.manifest, now=current_time)
            if not await self._repository.consume_manifest_nonce(nonce=run.manifest.nonce, run_id=run.run_id):
                return await self._terminal(run, SandboxRunStatus.FAILED, "MANIFEST_REPLAY")
            if not await self._runner.accepts_manifest_image_digest(
                run.manifest.image_digest
            ):
                return await self._terminal(run, SandboxRunStatus.FAILED, "IMAGE_DIGEST_MISMATCH")
            if (
                self._runner.package_manifest_hash is not None
                and self._runner.package_manifest_hash != run.manifest.package_manifest_hash
            ):
                return await self._terminal(run, SandboxRunStatus.FAILED, "PACKAGE_MANIFEST_MISMATCH")
            code = await self._repository.get_analysis_code(
                project_id=run.project_id, code_version_id=run.code_version_id
            )
            dataset = await self._repository.get_dataset(project_id=run.project_id, dataset_id=run.dataset_id)
            if code is None or dataset is None:
                return await self._terminal(run, SandboxRunStatus.FAILED, "RUN_INPUT_NOT_FOUND")
            if hashlib.sha256(code.source_code.encode("utf-8")).hexdigest() != run.manifest.code_hash:
                return await self._terminal(run, SandboxRunStatus.FAILED, "CODE_HASH_MISMATCH")
            self._policy.ensure_allowed(code.source_code)
            dataset_bytes = await self._object_store.get_bytes(key=dataset.storage_key)
            if hashlib.sha256(dataset_bytes).hexdigest() != run.manifest.dataset_content_hash:
                return await self._terminal(run, SandboxRunStatus.FAILED, "DATASET_HASH_MISMATCH")
            result = await self._execute_with_heartbeat(
                run,
                ExecutionRequest(
                    run_id=run.run_id,
                    dataset_filename=dataset.filename,
                    dataset_bytes=dataset_bytes,
                    code=code.source_code,
                    random_seed=run.manifest.random_seed,
                    security=self._security_from_manifest(run),
                )
            )
            if result is None:
                return await self._repository.get_sandbox_run(
                    project_id=run.project_id, run_id=run.run_id
                )
            latest = await self._repository.get_sandbox_run(project_id=run.project_id, run_id=run.run_id)
            if latest is not None and latest.status is SandboxRunStatus.CANCELLED:
                return latest
            if result.timed_out:
                return await self._terminal(run, SandboxRunStatus.TIMED_OUT, "SANDBOX_TIMED_OUT")
            if result.exit_code != 0:
                return await self._terminal(run, SandboxRunStatus.FAILED, "SANDBOX_EXECUTION_FAILED")
            for item in result.artifacts:
                if item.artifact_type not in {"result", "table", "chart", "diagnostic"}:
                    return await self._terminal(run, SandboxRunStatus.FAILED, "OUTPUT_ARTIFACT_TYPE_INVALID")
                storage_key = f"artifacts/{run.project_id}/{run.run_id}/{item.filename}"
                await self._object_store.put_bytes(
                    key=storage_key,
                    data=item.content,
                    content_type=self._artifact_media_type(item.filename),
                )
                await self._repository.save_artifact(
                    AnalysisArtifact(
                        project_id=run.project_id,
                        run_id=run.run_id,
                        artifact_type=item.artifact_type,  # type: ignore[arg-type]
                        filename=item.filename,
                        content_hash=hashlib.sha256(item.content).hexdigest(),
                        size_bytes=len(item.content),
                        storage_key=storage_key,
                    )
                )
            self.metrics.increment(
                "sandbox_artifacts_collected_total", value=len(result.artifacts)
            )
            completed = await self._terminal(run, SandboxRunStatus.COMPLETED_UNVALIDATED)
            if self._result_pipeline is None:
                return completed
            validation = await self._result_pipeline.validate_run(project_id=run.project_id, run_id=run.run_id)
            if validation.status is ResultValidationStatus.VALIDATED:
                # Interpretation is deliberately invoked only after a durable validation record exists.
                try:
                    await self._result_pipeline.interpret_validated(project_id=run.project_id, run_id=run.run_id)
                except Exception as error:
                    # Interpretation is optional enrichment; its outage must not invalidate
                    # an already validated, reviewable scientific result.
                    self.metrics.increment(
                        "sandbox_result_interpretation_total", labels={"result": "failed"}
                    )
                    self.events.emit(
                        "sandbox_result_interpretation_failed",
                        level=logging.WARNING,
                        run_id=run.run_id,
                        project_id=run.project_id,
                        worker_id=self._worker_id,
                        error_code=type(error).__name__,
                    )
            return await self._repository.get_sandbox_run(project_id=run.project_id, run_id=run.run_id)
        except CodePolicyViolation:
            return await self._terminal(run, SandboxRunStatus.POLICY_REJECTED, "CODE_POLICY_REJECTED")
        except ArtifactPolicyViolation:
            return await self._terminal(run, SandboxRunStatus.FAILED, "OUTPUT_ARTIFACT_POLICY_REJECTED")
        except RuntimeUnavailable:
            return await self._terminal(run, SandboxRunStatus.FAILED, "RUNTIME_UNAVAILABLE")
        except ManifestVerificationError:
            return await self._terminal(run, SandboxRunStatus.FAILED, "MANIFEST_VERIFICATION_FAILED")
        except Exception:
            return await self._terminal(run, SandboxRunStatus.FAILED, "SANDBOX_EXECUTION_FAILED")
        finally:
            self._active_run_id = None
            if self.probe_state is not None:
                self.probe_state.active_run_id = None
            self.metrics.set_gauge(
                "sandbox_worker_active_runs", 0, labels={"worker_id": self._worker_id}
            )
            self.metrics.observe(
                "sandbox_worker_run_duration_seconds", time.monotonic() - started
            )

    async def _execute_with_heartbeat(
        self, run: SandboxRun, request: ExecutionRequest
    ) -> ExecutionResult | None:
        execution = asyncio.create_task(self._runner.execute(request))
        try:
            while True:
                done, _ = await asyncio.wait(
                    {execution}, timeout=self._heartbeat_interval
                )
                if done:
                    return execution.result()
                latest = await self._repository.get_sandbox_run(
                    project_id=run.project_id, run_id=run.run_id
                )
                if latest is None or latest.status is SandboxRunStatus.CANCELLED:
                    self.metrics.increment(
                        "sandbox_worker_runtime_cancel_total",
                        labels={"reason": "user_cancelled" if latest else "run_missing"},
                    )
                    await self._stop_execution(run.run_id, execution)
                    return None
                renewed = await self._repository.renew_sandbox_run_lease(
                    run_id=run.run_id,
                    worker_id=self._worker_id,
                    now=datetime.now(timezone.utc),
                    lease_seconds=self._lease_seconds,
                )
                self.metrics.increment(
                    "sandbox_worker_lease_renew_total",
                    labels={"result": "renewed" if renewed else "lost"},
                )
                if not renewed:
                    await self._stop_execution(run.run_id, execution)
                    return None
        except asyncio.CancelledError:
            await self._stop_execution(run.run_id, execution)
            raise

    async def _stop_execution(
        self, run_id: str, execution: asyncio.Task[ExecutionResult]
    ) -> None:
        await self._runner.cancel(run_id)
        if not execution.done():
            execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)

    async def _terminal(self, run: SandboxRun, status: SandboxRunStatus, error_code: str | None = None) -> SandboxRun:
        latest = await self._repository.get_sandbox_run(project_id=run.project_id, run_id=run.run_id)
        if latest is not None and latest.status is SandboxRunStatus.CANCELLED:
            return latest
        base = latest or run
        updated = await self._repository.update_sandbox_run(
            base.model_copy(
                update={
                    "status": status,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "error_code": error_code,
                    "updated_at": datetime.now(timezone.utc),
                }
            ),
            changed_by=self._worker_id,
            reason=error_code,
        )
        self.metrics.increment(
            "sandbox_run_terminal_total", labels={"status": status.value}
        )
        self.events.emit(
            "sandbox_run_terminal",
            run_id=run.run_id,
            project_id=run.project_id,
            worker_id=self._worker_id,
            status=status.value,
            error_code=error_code,
            level=logging.ERROR if error_code else logging.INFO,
        )
        return updated

    @staticmethod
    def _security_from_manifest(run: SandboxRun) -> RuntimeSecuritySpec:
        limits = run.manifest.resource_limits
        if limits.get("network") != "none":
            raise ManifestVerificationError("manifest does not disable networking")
        try:
            return RuntimeSecuritySpec(
                cpu_limit=float(limits["cpu"]),
                memory_mb=int(limits["memory_mb"]),
                pid_limit=int(limits["pids"]),
                timeout_seconds=int(limits["timeout_seconds"]),
                temp_disk_mb=int(limits["temp_disk_mb"]),
                max_output_bytes=int(limits.get("max_output_bytes", 64 * 1024 * 1024)),
                max_artifact_bytes=int(limits.get("max_artifact_bytes", 16 * 1024 * 1024)),
                max_artifact_count=int(limits.get("max_artifact_count", 50)),
                max_log_bytes=int(limits.get("max_log_bytes", 64 * 1024)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestVerificationError("manifest resource limits are malformed") from exc

    @staticmethod
    def _artifact_media_type(filename: str) -> str:
        if filename.endswith(".csv"):
            return "text/csv"
        if filename.endswith(".png"):
            return "image/png"
        return "application/json"
