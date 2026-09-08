"""Stable integration ports. Production adapters live outside the S0 domain."""

from typing import Any, Protocol

from sandbox_service.domain.sessions import (
    ResearchContextSnapshot,
    SandboxEntrypoint,
)


class ProjectAIClient(Protocol):
    async def invoke_structured(
        self,
        *,
        project_id: str,
        operation: str,
        prompt_version: str,
        input_payload: dict[str, Any],
        output_schema: type[Any],
        correlation_id: str,
    ) -> dict[str, Any]: ...


class ResearchContextProvider(Protocol):
    async def resolve_snapshot(
        self,
        *,
        project_id: str,
        entrypoint: SandboxEntrypoint,
        source_resource_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> ResearchContextSnapshot: ...


class GraphSnapshotReader(Protocol):
    async def read_snapshot(
        self, *, project_id: str, graph_version_id: str, actor_id: str
    ) -> dict[str, Any]: ...


class ObjectStore(Protocol):
    async def put_bytes(
        self, *, key: str, data: bytes, content_type: str
    ) -> str: ...

    async def get_bytes(self, *, key: str) -> bytes: ...

    async def delete(self, *, key: str) -> None: ...


class SandboxExecutor(Protocol):
    async def submit(self, *, manifest: dict[str, Any], correlation_id: str) -> str: ...

    async def cancel(self, *, run_id: str, correlation_id: str) -> None: ...


class AdoptionGateway(Protocol):
    async def create_proposal(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> str: ...
