"""Entrypoint for the dedicated literature-review worker process."""

from __future__ import annotations

import asyncio
import logging
import os

# Settings are cached, so select the worker role before importing application modules.
os.environ.setdefault("RUNTIME_ROLE", "worker")
os.environ.setdefault("WORKER_MODE", "external")

from src.config import get_settings
from src.logging_utils import event


def configure_worker_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s pid=%(process)d [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logging.getLogger().setLevel(level)
    logging.getLogger("src").setLevel(level)
    # Span export runs asynchronously and is not part of the review outcome.
    # Keep transport failures out of the user-facing worker log.
    logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter").setLevel(logging.CRITICAL)


async def main() -> None:
    # Import application modules only after the worker logger is configured.
    from src.api.routers.literature_reviews import job_service, repository
    from src.services.worker_runtime import LitReviewWorkerRuntime

    settings = get_settings()
    repository.initialize()
    event(
        logging.getLogger("src.worker_main"),
        "worker.started",
        state={"job_id": "worker", "run_id": "worker", "execution_mode": settings.worker_mode},
        worker_mode=settings.worker_mode,
        log_level=settings.log_level,
    )
    runtime = LitReviewWorkerRuntime(repository, job_service, settings)
    await runtime.start()
    try:
        await asyncio.Event().wait()
    finally:
        await runtime.stop()


if __name__ == "__main__":
    configure_worker_logging()
    asyncio.run(main())
