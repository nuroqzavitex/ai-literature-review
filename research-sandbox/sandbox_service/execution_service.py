"""Create project-scoped idempotent runs and enforce approval/manifest gates."""

from __future__ import annotations

import secrets
from typing import Any, Protocol
from uuid import uuid4

from sandbox_service.code_generation_service import CodeGenerationService
from sandbox_service.domain.analysis_plans import AnalysisPlanStatus, AnalysisPlanVersion
from sandbox_service.domain.datasets import DatasetRecord
from sandbox_service.domain.errors import AnalysisPlanNotApproved, SandboxRunNotFound, SandboxRunStateError
from sandbox_service.domain.execution import (
    AnalysisArtifact,
    CreateSandboxRunRequest,
    QueuedRunResponse,
    SandboxExecutionManifest,
    SandboxRun,
    SandboxRunStatus,
)
from sandbox_service.execution.manifest import ManifestSigner
from sandbox_service.execution.runner import RuntimeSecuritySpec


class ExecutionRepository(Protocol):
    async def get_dataset(self, *, project_id: str, dataset_id: str, include_deleted: bool = False) -> DatasetRecord | None: ...

    async def get_analysis_plan(self, *, project_id: str, plan_id: str, version: int) -> AnalysisPlanVersion | None: ...

    async def get_sandbox_run_by_idempotency(self, *, project_id: str, idempotency_key: str) -> SandboxRun | None: ...

    async def create_sandbox_run(self, run: SandboxRun) -> SandboxRun: ...

    async def get_sandbox_run(self, *, project_id: str, run_id: str) -> SandboxRun | None: ...

    async def update_sandbox_run(self, run: SandboxRun, *, changed_by: str, reason: str | None = None) -> SandboxRun: ...

    async def list_artifacts(self, *, project_id: str, run_id: str) -> list[AnalysisArtifact]: ...


class ExecutionService:
    def __init__(
        self,
        *,
        repository: ExecutionRepository,
        code_generation: CodeGenerationService,
        manifest_signer: ManifestSigner,
        image_digest: str,
        package_manifest_hash: str,
        security: RuntimeSecuritySpec | None = None,
    ) -> None:
        self._repository = repository
        self._code_generation = code_generation
        self._signer = manifest_signer
        self._image_digest = image_digest
        self._package_manifest_hash = package_manifest_hash
        self._security = security or RuntimeSecuritySpec()

    async def queue_run(
        self,
        *,
        project_id: str,
        plan_id: str,
        plan_version: int,
        actor_id: str,
        idempotency_key: str,
        request: CreateSandboxRunRequest,
        correlation_id: str | None = None,
    ) -> SandboxRun:
        existing = await self._repository.get_sandbox_run_by_idempotency(
            project_id=project_id, idempotency_key=idempotency_key
        )
        if existing is not None:
            if (
                existing.plan_id != plan_id
                or existing.plan_version != plan_version
                or existing.manifest.random_seed != request.random_seed
            ):
                raise SandboxRunStateError(
                    "Idempotency-Key was already used for a different run request"
                )
            return existing
        plan = await self._repository.get_analysis_plan(
            project_id=project_id, plan_id=plan_id, version=plan_version
        )
        if plan is None or plan.status is not AnalysisPlanStatus.APPROVED:
            raise AnalysisPlanNotApproved("An approved immutable analysis plan is required")
        dataset = await self._repository.get_dataset(project_id=project_id, dataset_id=plan.dataset_id)
        if dataset is None:
            raise AnalysisPlanNotApproved("The approved plan dataset is unavailable")
        code, decision = await self._code_generation.generate(
            project_id=project_id,
            plan_id=plan_id,
            plan_version=plan_version,
            correlation_id=correlation_id,
        )
        run_id, operation_id = str(uuid4()), str(uuid4())
        manifest = self._signer.sign(
            SandboxExecutionManifest(
                operation_id=operation_id,
                run_id=run_id,
                project_id=project_id,
                dataset_id=dataset.dataset_id,
                dataset_content_hash=dataset.content_hash,
                plan_id=plan.plan_id,
                plan_version=plan.version,
                plan_hash=plan.plan_hash,
                plan_decision_id=decision.decision_id,
                code_version_id=code.code_version_id,
                code_hash=code.code_hash,
                image_digest=self._image_digest,
                package_manifest_hash=self._package_manifest_hash,
                random_seed=request.random_seed,
                resource_limits={
                    "cpu": self._security.cpu_limit,
                    "memory_mb": self._security.memory_mb,
                    "pids": self._security.pid_limit,
                    "timeout_seconds": self._security.timeout_seconds,
                    "temp_disk_mb": self._security.temp_disk_mb,
                    "max_output_bytes": self._security.max_output_bytes,
                    "max_artifact_bytes": self._security.max_artifact_bytes,
                    "max_artifact_count": self._security.max_artifact_count,
                    "max_log_bytes": self._security.max_log_bytes,
                    "network": "none",
                },
                nonce=secrets.token_urlsafe(24),
            )
        )
        return await self._repository.create_sandbox_run(
            SandboxRun(
                run_id=run_id,
                operation_id=operation_id,
                project_id=project_id,
                dataset_id=dataset.dataset_id,
                plan_id=plan.plan_id,
                plan_version=plan.version,
                plan_decision_id=decision.decision_id,
                code_version_id=code.code_version_id,
                idempotency_key=idempotency_key,
                status=SandboxRunStatus.QUEUED,
                manifest=manifest,
            )
        )

    async def get_run(self, *, project_id: str, run_id: str) -> SandboxRun:
        run = await self._repository.get_sandbox_run(project_id=project_id, run_id=run_id)
        if run is None:
            raise SandboxRunNotFound("Sandbox run was not found in this project")
        return run

    async def cancel_run(self, *, project_id: str, run_id: str, actor_id: str) -> SandboxRun:
        run = await self.get_run(project_id=project_id, run_id=run_id)
        if run.status not in {SandboxRunStatus.PENDING_APPROVAL, SandboxRunStatus.QUEUED, SandboxRunStatus.RUNNING}:
            raise SandboxRunStateError("Only pending, queued, or running runs can be cancelled")
        return await self._repository.update_sandbox_run(
            run.model_copy(update={"status": SandboxRunStatus.CANCELLED, "lease_owner": None, "lease_expires_at": None}),
            changed_by=actor_id,
            reason="cancelled_by_user",
        )

    async def list_artifacts(self, *, project_id: str, run_id: str) -> list[AnalysisArtifact]:
        await self.get_run(project_id=project_id, run_id=run_id)
        return await self._repository.list_artifacts(project_id=project_id, run_id=run_id)

    @staticmethod
    def queued_response(run: SandboxRun) -> QueuedRunResponse:
        return QueuedRunResponse(
            operation_id=run.operation_id,
            resource_id=run.run_id,
            status_url=f"/api/v1/projects/{run.project_id}/sandbox-runs/{run.run_id}",
        )
