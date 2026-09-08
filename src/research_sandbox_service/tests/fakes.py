"""Fake adapters used by S0 tests; none touches the main backend or a worker."""

from typing import Any

from sandbox_service.domain.errors import SourceNotReviewed
from sandbox_service.domain.sessions import ResearchContextSnapshot, SandboxEntrypoint


class FakeProjectAIClient:
    def __init__(self, responses: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses = responses or []

    async def invoke_structured(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.responses.pop(0) if self.responses else {}


class FakeResearchContextProvider:
    def __init__(self, snapshots: dict[tuple[str, str], ResearchContextSnapshot] | None = None) -> None:
        self.snapshots = snapshots or {}
        self.calls: list[dict[str, str]] = []

    async def resolve_snapshot(
        self,
        *,
        project_id: str,
        entrypoint: SandboxEntrypoint,
        source_resource_id: str,
        actor_id: str,
        correlation_id: str,
    ) -> ResearchContextSnapshot:
        self.calls.append({"project_id": project_id, "source_resource_id": source_resource_id})
        snapshot = self.snapshots.get((project_id, source_resource_id))
        if snapshot is None:
            raise SourceNotReviewed("Source is not available in this project")
        return snapshot


class FakeGraphSnapshotReader:
    def __init__(self, snapshots: dict[tuple[str, str], dict[str, Any]] | None = None) -> None:
        self.snapshots = snapshots or {}
        self.calls: list[dict[str, str]] = []

    async def read_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        project_id = kwargs["project_id"]
        graph_version_id = kwargs["graph_version_id"]
        self.calls.append({"project_id": project_id, "graph_version_id": graph_version_id})
        if (project_id, graph_version_id) not in self.snapshots:
            raise KeyError(graph_version_id)
        return self.snapshots[(project_id, graph_version_id)]


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_bytes(self, *, key: str, data: bytes, content_type: str) -> str:
        self.objects[key] = data
        return key

    async def get_bytes(self, *, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)


class FakeSandboxExecutor:
    def __init__(self) -> None:
        self.submissions: list[dict[str, Any]] = []

    async def submit(self, *, manifest: dict[str, Any], correlation_id: str) -> str:
        self.submissions.append(manifest)
        return "run_fake"

    async def cancel(self, *, run_id: str, correlation_id: str) -> None:
        return None


class FakeAdoptionGateway:
    async def create_proposal(self, **kwargs: Any) -> str:
        return "proposal_fake"
