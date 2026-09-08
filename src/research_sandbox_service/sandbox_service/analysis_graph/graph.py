"""Small S5 orchestration facade: code generation/policy precede durable queueing."""

from sandbox_service.domain.execution import CreateSandboxRunRequest, SandboxRun
from sandbox_service.execution_service import ExecutionService


class AnalysisGraph:
    def __init__(self, *, execution_service: ExecutionService) -> None:
        self._execution_service = execution_service

    async def confirm_execution(
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
        return await self._execution_service.queue_run(
            project_id=project_id,
            plan_id=plan_id,
            plan_version=plan_version,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            request=request,
            correlation_id=correlation_id,
        )
