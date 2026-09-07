"""Durable PostgreSQL-backed runtime for literature-review jobs.

The API creates only durable queued rows.  This runtime claims those rows with
the repository lease and executes them in a dedicated worker process, mirroring
the external-dispatch separation used by the reference platform.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from collections.abc import Awaitable
from uuid import uuid4

from src.agents.litreview.application.jobs import LitReviewJobService
from src.agents.litreview.infrastructure.repositories.jobs import JobRepository
from src.config import Settings
from src.logging_utils import event, failure_code
from src.services.redis_jobs import RedisJobNotifier

logger = logging.getLogger(__name__)


class LitReviewWorkerRuntime:
    """Claims and executes durable queued/resume jobs with bounded concurrency."""

    def __init__(
        self,
        repository: JobRepository,
        job_service: LitReviewJobService,
        settings: Settings,
        notifier: RedisJobNotifier | None = None,
    ) -> None:
        self.repository = repository
        self.job_service = job_service
        self.settings = settings
        self.notifier = notifier or RedisJobNotifier(settings)
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        self._tasks: set[asyncio.Task[None]] = set()
        self._scanner: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    @property
    def active_jobs(self) -> int:
        return len(self._tasks)

    async def start(self) -> None:
        if self._scanner is not None:
            return
        event(
            logger,
            "worker.started",
            worker_id=self.worker_id,
            mode=self.settings.worker_mode,
            concurrency=self.settings.worker_max_concurrent_jobs,
        )
        await self.notifier.start(consumer=self.worker_id)
        self._scanner = asyncio.create_task(self._run_loop(), name="litreview-job-worker")

    async def stop(self) -> None:
        self._stopping.set()
        tasks = [*self._tasks]
        if self._scanner is not None:
            self._scanner.cancel()
            tasks.append(self._scanner)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.notifier.close()
        self._scanner = None

    async def dispatch_once(self) -> None:
        """Claim only as many rows as this process can execute now."""
        available = self.settings.worker_max_concurrent_jobs - self.active_jobs
        if available <= 0:
            return

        # Resume jobs first so a submitted human review does not wait behind a
        # newly-created search.  Both claim methods use DB row locks + leases.
        for job_id, payload in self.repository.get_resuming_jobs(
            limit=available, worker_id=self.worker_id, lease_seconds=self.settings.worker_lease_seconds
        ):
            self._launch(
                job_id,
                self.job_service.resume(
                    job_id,
                    payload,
                    worker_id=self.worker_id,
                    execution_fence=payload.get("_execution_fence"),
                ),
                "resume",
            )
        available = self.settings.worker_max_concurrent_jobs - self.active_jobs
        if available <= 0:
            return
        for job_id, initial_state in self.repository.claim_queued_jobs(
            limit=available, worker_id=self.worker_id, lease_seconds=self.settings.worker_lease_seconds
        ):
            self._launch(
                job_id,
                self.job_service.run(
                    job_id,
                    initial_state,
                    worker_id=self.worker_id,
                    execution_fence=initial_state.get("_execution_fence"),
                ),
                "run",
            )

    def _launch(self, job_id: str, coroutine: Awaitable[None], operation: str) -> None:
        task = asyncio.create_task(coroutine, name=f"litreview-{operation}:{job_id}")
        self._tasks.add(task)

        def _completed(finished: asyncio.Task[None]) -> None:
            self._tasks.discard(finished)
            if finished.cancelled():
                return
            try:
                finished.result()
            except Exception:  # Service normally persists its own failure; keep worker alive.
                exc = finished.exception()
                event(
                    logger,
                    "worker.task_failed",
                    state={"job_id": job_id},
                    level=logging.ERROR,
                    worker_id=self.worker_id,
                    operation=operation,
                    error_type=type(exc).__name__ if exc else "unknown",
                    failure_code=failure_code(exc or "unknown"),
                )

        task.add_done_callback(_completed)

    async def _run_loop(self) -> None:
        next_heartbeat = 0.0
        while not self._stopping.is_set():
            try:
                if time.monotonic() >= next_heartbeat:
                    reclaimed = self.repository.reclaim_expired_jobs()
                    if reclaimed:
                        event(
                            logger,
                            "worker.jobs_reclaimed",
                            level=logging.WARNING,
                            worker_id=self.worker_id,
                            job_ids=reclaimed,
                            reclaimed_count=len(reclaimed),
                        )
                    self.repository.renew_worker_leases(self.worker_id, self.settings.worker_lease_seconds)
                    next_heartbeat = time.monotonic() + self.settings.worker_heartbeat_seconds
                await self.dispatch_once()
                if self.notifier.subscribed:
                    available = max(1, self.settings.worker_max_concurrent_jobs - self.active_jobs)
                    pending = await self.notifier.reclaim_pending(available, self.settings.worker_lease_seconds * 1000)
                    fresh = await self.notifier.read_requests(available)
                    for message_id, _ in [*pending, *fresh]:
                        await self.dispatch_once()
                        await self.notifier.acknowledge(message_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                event(
                    logger,
                    "worker.dispatch_failed",
                    level=logging.ERROR,
                    worker_id=self.worker_id,
                    error_type=type(exc).__name__,
                    failure_code=failure_code(exc),
                )
            if self.notifier.subscribed:
                # XREADGROUP above already blocks; keep this tiny yield so a
                # full worker does not spin while messages remain pending.
                await asyncio.sleep(0)
            else:
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self.settings.worker_poll_seconds)
                except TimeoutError:
                    pass
