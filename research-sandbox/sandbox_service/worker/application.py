"""Lifecycle loop and probes for a separately deployed durable worker."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os

from sandbox_service.observability import (
    SandboxMetrics,
    StructuredEventLogger,
    WorkerProbeServer,
    WorkerProbeState,
)
from sandbox_service.worker.execution_worker import DurableExecutionWorker


_LOGGER = logging.getLogger(__name__)


def _debug_runtime_errors_enabled() -> bool:
    environment = os.getenv("SANDBOX_ENVIRONMENT", "production").strip().lower()
    demo_mode = os.getenv("SANDBOX_DEMO_MODE", "false").strip().lower()
    return environment == "development" or demo_mode in {"1", "true", "yes", "on"}


class WorkerApplication:
    def __init__(
        self,
        *,
        worker: DurableExecutionWorker,
        probe_server: WorkerProbeServer,
        state: WorkerProbeState,
        metrics: SandboxMetrics,
        poll_interval_seconds: float = 1.0,
        event_logger: StructuredEventLogger | None = None,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        self.worker = worker
        self.probe_server = probe_server
        self.state = state
        self.metrics = metrics
        self.poll_interval_seconds = poll_interval_seconds
        self.events = event_logger or StructuredEventLogger()

    async def run(self, *, stop_event: asyncio.Event | None = None) -> None:
        stop = stop_event or asyncio.Event()
        await self.probe_server.start()
        self.events.emit("sandbox_worker_started", worker_id="worker")
        try:
            while not stop.is_set():
                try:
                    self.state.ready = await self.worker.ready()
                    self.metrics.set_gauge(
                        "sandbox_worker_ready", 1 if self.state.ready else 0
                    )
                    if not self.state.ready:
                        self.state.last_error_code = "DEPENDENCY_NOT_READY"
                        await self._wait(stop)
                        continue
                    self.state.last_error_code = None
                    processed = await self.worker.process_next()
                    self.state.last_poll_at = datetime.now(timezone.utc)
                    if processed is None:
                        await self._wait(stop)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    if _debug_runtime_errors_enabled():
                        _LOGGER.exception("sandbox_worker_loop_exception")
                    self.state.ready = False
                    self.state.last_error_code = "WORKER_LOOP_ERROR"
                    self.metrics.increment(
                        "sandbox_worker_loop_error_total", labels={"error": "internal"}
                    )
                    self.events.emit(
                        "sandbox_worker_loop_error",
                        level=logging.ERROR,
                        error_code="WORKER_LOOP_ERROR",
                    )
                    await self._wait(stop)
        finally:
            self.state.accepting_work = False
            self.state.ready = False
            self.metrics.set_gauge("sandbox_worker_ready", 0)
            await self.probe_server.close()
            self.events.emit("sandbox_worker_stopped", worker_id="worker")

    async def _wait(self, stop: asyncio.Event) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=self.poll_interval_seconds)
        except TimeoutError:
            pass
