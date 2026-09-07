import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers.document_reviews import router as document_reviews_router
from src.api.routers.literature_reviews import job_service, repository, router
from src.api.routers.research_copilot import router as v2_router
from src.api.routers.research_copilot import v2_repository
from src.api.routers.sandbox import router as sandbox_router
from src.api.routers.sandbox_internal import router as sandbox_internal_router
from src.config import get_settings
from src.logging_utils import event, failure_code
from src.services.worker_runtime import LitReviewWorkerRuntime

logger = logging.getLogger("litreview.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    repository.initialize()
    v2_repository.initialize()
    worker: LitReviewWorkerRuntime | None = None
    if settings.worker_mode == "embedded":
        worker = LitReviewWorkerRuntime(repository, job_service, settings)
        await worker.start()

    yield
    print("Shutting down...")
    if worker is not None:
        await worker.stop()


app = FastAPI(
    title="LitReview Agent",
    description="Grounded academic literature review and research-gap MVP",
    version="0.1.0",
    lifespan=lifespan,
)

LOG_FORMAT = "%(asctime)s %(levelname)-5s pid=%(process)d [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: int) -> None:
    """Apply one timestamped format even when Uvicorn initialized logging first."""
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    loggers = [
        logging.getLogger(),
        logging.getLogger("uvicorn"),
        logging.getLogger("uvicorn.error"),
        logging.getLogger("uvicorn.access"),
    ]
    loggers.extend(
        candidate for candidate in logging.Logger.manager.loggerDict.values() if isinstance(candidate, logging.Logger)
    )
    for configured_logger in loggers:
        if configured_logger.name in {"root", "uvicorn", "uvicorn.error", "uvicorn.access"}:
            configured_logger.setLevel(level)
        for handler in configured_logger.handlers:
            handler.setFormatter(formatter)


settings = get_settings()
log_level = getattr(logging, settings.log_level, logging.INFO)
configure_logging(log_level)

# Uvicorn configures logging before importing this module, which makes
# ``basicConfig`` a no-op. Set the existing root logger explicitly so workflow
# progress emitted by ``src.*`` is written to the development log as well.
logging.getLogger().setLevel(log_level)
logging.getLogger("src").setLevel(log_level)
# Telemetry is best-effort.  A slow/unreachable Langfuse endpoint must never
# make an interactive review look like it failed or flood the worker log.
logging.getLogger("opentelemetry.exporter.otlp.proto.http.trace_exporter").setLevel(logging.CRITICAL)
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
origins.extend(
    [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started_at = time.perf_counter()
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        event(
            logger,
            "http.request_failed",
            state={"request_id": request_id},
            level=logging.ERROR,
            method=request.method,
            path=request.url.path,
            duration_ms=round(elapsed_ms),
            error_type=type(exc).__name__,
            failure_code=failure_code(exc),
        )
        raise
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    response.headers["X-Request-ID"] = request_id
    is_status_poll = request.method == "GET" and (
        request.url.path.endswith("/status") or "/reviews/job_" in request.url.path
    )
    event(
        logger,
        "http.request_completed",
        state={"request_id": request_id},
        level=logging.DEBUG if is_status_poll else logging.INFO,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(elapsed_ms),
    )
    return response


app.include_router(router, prefix="/api/v1")
app.include_router(document_reviews_router, prefix="/api/v1")
app.include_router(v2_router, prefix="/api/v1")
# The router is always registered so the frontend can read disabled capabilities.
# Its gateway remains fail-closed and performs no outbound request while
# SANDBOX_ENABLED=false.
app.include_router(sandbox_router, prefix="/api/v1")
app.include_router(sandbox_internal_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "litreview-agent", "env": settings.app_env}
