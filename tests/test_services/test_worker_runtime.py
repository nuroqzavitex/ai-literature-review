import asyncio
from types import SimpleNamespace

import pytest

from src.services.worker_runtime import LitReviewWorkerRuntime


class FakeRepository:
    def __init__(self) -> None:
        self.resume_limits: list[int | None] = []
        self.queued_limits: list[int | None] = []

    def get_resuming_jobs(self, limit: int | None = None, **_kwargs):
        self.resume_limits.append(limit)
        return [("resume-job", {"approved": True})]

    def claim_queued_jobs(self, limit: int | None = None, **_kwargs):
        self.queued_limits.append(limit)
        return [("queued-job", {"original_topic": "test"})]


class FakeJobService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def run(self, job_id: str, payload: dict, **_kwargs) -> None:
        self.calls.append(("run", job_id))

    async def resume(self, job_id: str, payload: dict, **_kwargs) -> None:
        self.calls.append(("resume", job_id))


@pytest.mark.asyncio
async def test_worker_claims_resume_before_queued_work_and_respects_capacity():
    repository = FakeRepository()
    service = FakeJobService()
    settings = SimpleNamespace(
        worker_mode="external",
        worker_max_concurrent_jobs=2,
        worker_poll_seconds=1.0,
        redis_enabled=False,
        worker_lease_seconds=45,
        worker_heartbeat_seconds=10,
    )
    worker = LitReviewWorkerRuntime(repository, service, settings)

    await worker.dispatch_once()
    while worker.active_jobs:
        await asyncio.sleep(0)

    assert service.calls == [("resume", "resume-job"), ("run", "queued-job")]
    assert repository.resume_limits == [2]
    assert repository.queued_limits == [1]
