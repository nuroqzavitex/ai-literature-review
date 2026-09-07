from types import SimpleNamespace

import pytest

from src.services.redis_jobs import RedisJobNotifier, RedisJobStatusCache


def settings():
    return SimpleNamespace(
        redis_enabled=True,
        redis_url="redis://unused:6379/0",
        redis_job_stream="test:jobs",
        redis_job_consumer_group="test-workers",
        redis_stream_block_ms=1000,
        redis_status_ttl_seconds=30,
    )


class SyncRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class AsyncRedis:
    def __init__(self) -> None:
        self.added: list[tuple[str, dict[str, str]]] = []

    async def ping(self) -> bool:
        return True

    async def xadd(self, stream: str, payload: dict[str, str]) -> None:
        self.added.append((stream, payload))

    async def aclose(self) -> None:
        return None


class StreamRedis(AsyncRedis):
    def __init__(self) -> None:
        super().__init__()
        self.group: tuple[str, str, str] | None = None
        self.acks: list[tuple[str, str, str]] = []

    async def xgroup_create(self, stream: str, group: str, *, id: str, mkstream: bool) -> None:
        self.group = (stream, group, id)

    async def xreadgroup(self, group: str, consumer: str, streams: dict[str, str], *, count: int, block: int):
        return [("test:jobs", [("1-0", {"job_id": "job-1", "operation": "run"})])]

    async def xautoclaim(self, stream: str, group: str, consumer: str, min_idle_ms: int, start_id: str, *, count: int):
        return ("0-0", [("0-1", {"job_id": "job-old", "operation": "resume"})], [])

    async def xack(self, stream: str, group: str, message_id: str) -> None:
        self.acks.append((stream, group, message_id))


def test_status_cache_reads_and_invalidates():
    cache = RedisJobStatusCache(settings(), client=SyncRedis())
    cache.set("job-1", {"status": "running", "papers_found": 2})

    assert cache.get("job-1") == {"status": "running", "papers_found": 2}
    cache.invalidate("job-1")
    assert cache.get("job-1") is None


@pytest.mark.asyncio
async def test_notifier_appends_durable_job_dispatch_event():
    client = AsyncRedis()
    notifier = RedisJobNotifier(settings(), client=client)

    await notifier.notify("job-1", "run")

    assert client.added == [("test:jobs", {"job_id": "job-1", "operation": "run"})]


@pytest.mark.asyncio
async def test_stream_consumer_group_reads_reclaims_and_acknowledges():
    client = StreamRedis()
    notifier = RedisJobNotifier(settings(), client=client)

    assert await notifier.start(consumer="worker-a") is True
    assert client.group == ("test:jobs", "test-workers", "0-0")
    assert await notifier.read_requests(2) == [("1-0", {"job_id": "job-1", "operation": "run"})]
    assert await notifier.reclaim_pending(2, 45_000) == [("0-1", {"job_id": "job-old", "operation": "resume"})]
    await notifier.acknowledge("1-0")
    assert client.acks == [("test:jobs", "test-workers", "1-0")]
