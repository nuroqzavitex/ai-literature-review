"""Fail-closed worker process entrypoint.

Production supplies ``SANDBOX_WORKER_FACTORY=package.module:create_worker``.  The
factory owns deployment-specific database/object-store credentials and returns a
fully configured ``DurableExecutionWorker``.  No in-memory fallback is allowed.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import os
import re
import signal
from typing import Callable

from sandbox_service.observability import (
    SandboxMetrics,
    StructuredEventLogger,
    WorkerProbeServer,
    WorkerProbeState,
)
from sandbox_service.worker.application import WorkerApplication
from sandbox_service.worker.execution_worker import DurableExecutionWorker


_FACTORY_PATH = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$"
)


def load_worker_factory(path: str) -> Callable[[], object]:
    if not _FACTORY_PATH.fullmatch(path):
        raise RuntimeError("SANDBOX_WORKER_FACTORY must be a module:function path")
    module_name, function_name = path.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, function_name, None)
    if not callable(factory):
        raise RuntimeError("configured worker factory is not callable")
    return factory


async def build_application_from_environment() -> WorkerApplication:
    factory_path = os.getenv("SANDBOX_WORKER_FACTORY", "")
    if not factory_path:
        raise RuntimeError("SANDBOX_WORKER_FACTORY is required; refusing in-memory worker startup")
    result = load_worker_factory(factory_path)()
    worker = await result if inspect.isawaitable(result) else result
    if not isinstance(worker, DurableExecutionWorker):
        raise RuntimeError("worker factory returned an invalid object")

    metrics = worker.metrics
    state = worker.probe_state or WorkerProbeState()
    worker.probe_state = state
    host = os.getenv("SANDBOX_WORKER_PROBE_HOST", "0.0.0.0")
    port = int(os.getenv("SANDBOX_WORKER_PROBE_PORT", "8090"))
    poll_interval = float(os.getenv("SANDBOX_WORKER_POLL_SECONDS", "1"))
    return WorkerApplication(
        worker=worker,
        probe_server=WorkerProbeServer(
            state=state, metrics=metrics, host=host, port=port
        ),
        state=state,
        metrics=metrics,
        poll_interval_seconds=poll_interval,
        event_logger=worker.events,
    )


async def _run() -> None:
    application = await build_application_from_environment()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for selected_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(selected_signal, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    await application.run(stop_event=stop)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
