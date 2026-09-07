"""Optional Redis acceleration for durable literature-review jobs.

PostgreSQL remains the source of truth. Redis only makes job dispatch and
status polling fast, so a Redis outage degrades to database polling rather than
dropping work.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis
import redis.asyncio as aioredis

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)


class RedisJobNotifier:
    """Redis Streams dispatch with consumer-group recovery.

    PostgreSQL remains authoritative for execution ownership; the stream gives
    workers durable, acknowledged wake-up messages and lets another consumer
    reclaim messages left pending by a crashed worker.
    """

    def __init__(self, settings: Settings | None = None, client: aioredis.Redis | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._consumer: str | None = None
        self._available = False

    @property
    def enabled(self) -> bool:
        return self.settings.redis_enabled

    @property
    def subscribed(self) -> bool:
        return self._available and self._consumer is not None

    async def start(self, *, consumer: str | None = None) -> bool:
        if not self.enabled:
            return False
        try:
            if self._client is None:
                self._client = aioredis.from_url(
                    self.settings.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                )
            await self._client.ping()
            self._available = True
            if consumer:
                self._consumer = consumer
                try:
                    await self._client.xgroup_create(
                        self.settings.redis_job_stream,
                        self.settings.redis_job_consumer_group,
                        id="0-0",
                        mkstream=True,
                    )
                except redis.ResponseError as exc:
                    if "BUSYGROUP" not in str(exc):
                        raise
            return True
        except redis.RedisError as exc:
            logger.warning("Redis unavailable; falling back to PostgreSQL polling: %s", exc)
            self._available = False
            return False

    async def notify(self, job_id: str, operation: str) -> None:
        if not self.enabled:
            return
        if not self._available and not await self.start():
            return
        assert self._client is not None
        try:
            await self._client.xadd(
                self.settings.redis_job_stream,
                {"job_id": job_id, "operation": operation},
            )
        except redis.RedisError as exc:
            self._available = False
            logger.warning("Redis stream enqueue failed for %s; database worker scan will recover it: %s", job_id, exc)

    async def read_requests(self, count: int) -> list[tuple[str, dict[str, str]]]:
        if not self.subscribed or self._client is None:
            return []
        try:
            records = await self._client.xreadgroup(
                self.settings.redis_job_consumer_group,
                self._consumer,
                {self.settings.redis_job_stream: ">"},
                count=count,
                block=self.settings.redis_stream_block_ms,
            )
            return [(message_id, dict(fields)) for _, messages in records for message_id, fields in messages]
        except redis.RedisError as exc:
            self._available = False
            logger.warning("Redis stream read failed; falling back to PostgreSQL polling: %s", exc)
            return []

    async def reclaim_pending(self, count: int, min_idle_ms: int) -> list[tuple[str, dict[str, str]]]:
        if not self.subscribed or self._client is None:
            return []
        try:
            _, messages, _ = await self._client.xautoclaim(
                self.settings.redis_job_stream,
                self.settings.redis_job_consumer_group,
                self._consumer,
                min_idle_ms,
                "0-0",
                count=count,
            )
            return [(message_id, dict(fields)) for message_id, fields in messages]
        except redis.RedisError as exc:
            self._available = False
            logger.warning("Redis pending-message reclaim failed: %s", exc)
            return []

    async def acknowledge(self, message_id: str) -> None:
        if not self.subscribed or self._client is None:
            return
        try:
            await self._client.xack(
                self.settings.redis_job_stream,
                self.settings.redis_job_consumer_group,
                message_id,
            )
        except redis.RedisError as exc:
            logger.warning("Redis stream acknowledgement failed for %s: %s", message_id, exc)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


class RedisJobStatusCache:
    """Short-lived, write-invalidated cache for high-frequency status polling."""

    def __init__(self, settings: Settings | None = None, client: redis.Redis | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client

    def _key(self, job_id: str) -> str:
        return f"litreview:job-status:{job_id}"

    def _connection(self) -> redis.Redis | None:
        if not self.settings.redis_enabled:
            return None
        if self._client is None:
            self._client = redis.Redis.from_url(
                self.settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=0.1,
                socket_timeout=0.1,
            )
        return self._client

    def get(self, job_id: str) -> dict[str, Any] | None:
        try:
            client = self._connection()
            raw = client.get(self._key(job_id)) if client is not None else None
            value = json.loads(raw) if raw else None
            return value if isinstance(value, dict) else None
        except (redis.RedisError, json.JSONDecodeError) as exc:
            logger.debug("Redis status-cache read failed: %s", exc)
            return None

    def set(self, job_id: str, value: dict[str, Any]) -> None:
        try:
            client = self._connection()
            if client is not None:
                client.setex(
                    self._key(job_id), self.settings.redis_status_ttl_seconds, json.dumps(value, ensure_ascii=False)
                )
        except redis.RedisError as exc:
            logger.debug("Redis status-cache write failed: %s", exc)

    def invalidate(self, job_id: str) -> None:
        try:
            client = self._connection()
            if client is not None:
                client.delete(self._key(job_id))
        except redis.RedisError as exc:
            logger.debug("Redis status-cache invalidation failed: %s", exc)


_notifier: RedisJobNotifier | None = None


def get_job_notifier() -> RedisJobNotifier:
    global _notifier
    if _notifier is None:
        _notifier = RedisJobNotifier()
    return _notifier
