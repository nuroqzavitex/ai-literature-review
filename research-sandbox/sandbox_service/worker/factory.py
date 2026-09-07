"""Deployment factory for the durable PostgreSQL/S3/Docker worker."""

from __future__ import annotations

import importlib
import inspect
import logging
import os
from pathlib import Path
from typing import Any

from sandbox_service.config import SandboxSettings
from sandbox_service.execution import DockerRuntimeLauncher, EphemeralRunner, NativeRuntimeLauncher
from sandbox_service.execution.manifest import ManifestSigner
from sandbox_service.repositories import PostgresSandboxRepository
from sandbox_service.result_service import ResultReviewService
from sandbox_service.storage import LocalObjectStore, S3ObjectStore
from sandbox_service.worker.execution_worker import DurableExecutionWorker


_LOGGER = logging.getLogger(__name__)


def _resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


async def _project_ai_from_environment() -> Any | None:
    factory_path = os.getenv("SANDBOX_PROJECT_AI_FACTORY", "")
    if not factory_path:
        return None
    if ":" not in factory_path:
        raise RuntimeError("SANDBOX_PROJECT_AI_FACTORY must use module:function syntax")
    module_name, function_name = factory_path.split(":", 1)
    factory = getattr(importlib.import_module(module_name), function_name, None)
    if not callable(factory):
        raise RuntimeError("SANDBOX_PROJECT_AI_FACTORY does not resolve to a callable")
    result = factory()
    return await result if inspect.isawaitable(result) else result


async def select_runtime_launcher(
    *, launcher_kind: str, docker_launcher: Any, native_launcher: Any | None
) -> Any:
    """Choose one stable runtime at worker bootstrap.

    Auto mode prefers Docker. It falls back to the native runtime only when the
    signed runtime identity was explicitly configured as ``native-runtime``;
    silently changing execution identity after a manifest is signed is forbidden.
    """

    if launcher_kind == "docker":
        return docker_launcher
    if launcher_kind == "native":
        if native_launcher is None:
            raise RuntimeError(
                "native launcher requires SANDBOX_RUNTIME_IMAGE_DIGEST="
                "native-runtime@sha256:<SANDBOX_PACKAGE_MANIFEST_HASH>"
            )
        _LOGGER.info("sandbox_runtime_selected launcher=native reason=configured")
        return native_launcher
    if launcher_kind != "auto":
        raise RuntimeError("SANDBOX_RUNTIME_LAUNCHER must be auto, docker or native")
    if await docker_launcher.ready():
        _LOGGER.info("sandbox_runtime_selected launcher=docker reason=daemon_ready")
        return docker_launcher
    if native_launcher is not None and await native_launcher.ready():
        _LOGGER.warning(
            "sandbox_runtime_selected launcher=native reason=docker_unavailable"
        )
        return native_launcher
    raise RuntimeError(
        "no Sandbox runtime is ready: Docker daemon unavailable and native "
        "bubblewrap runtime is not safely configured"
    )


async def create_production_worker() -> DurableExecutionWorker:
    """Build the durable worker with a Docker or isolated native runtime."""

    settings = SandboxSettings()
    if settings.persistence_backend != "postgres" or settings.database_url is None:
        raise RuntimeError("durable worker requires SANDBOX_PERSISTENCE_BACKEND=postgres")
    launcher_kind = settings.runtime_launcher

    repository = PostgresSandboxRepository(
        str(settings.database_url),
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout_seconds=settings.database_pool_timeout_seconds,
    )
    if settings.object_storage_backend == "s3":
        if not settings.object_storage_bucket:
            raise RuntimeError("S3 object storage requires SANDBOX_OBJECT_STORAGE_BUCKET")
        object_store = S3ObjectStore(
            bucket=settings.object_storage_bucket,
            endpoint_url=settings.object_storage_endpoint,
            region_name=settings.object_storage_region,
            access_key_id=(
                settings.object_storage_access_key.get_secret_value()
                if settings.object_storage_access_key
                else None
            ),
            secret_access_key=(
                settings.object_storage_secret_key.get_secret_value()
                if settings.object_storage_secret_key
                else None
            ),
            server_side_encryption=settings.object_storage_server_side_encryption,
        )
    elif launcher_kind in {"auto", "native"}:
        object_store = LocalObjectStore(
            _resolve(Path(__file__).resolve().parents[2], settings.local_storage_path)
        )
    else:
        raise RuntimeError(
            "Docker durable worker requires shared S3-compatible object storage"
        )
    ai_client = await _project_ai_from_environment()
    if settings.result_interpretation_enabled and ai_client is None:
        raise RuntimeError(
            "result interpretation is enabled but SANDBOX_PROJECT_AI_FACTORY is not configured"
        )

    project_root = Path(__file__).resolve().parents[2]
    docker_launcher = DockerRuntimeLauncher(
        image_digest=settings.runtime_image_digest,
        package_manifest_hash=settings.package_manifest_hash,
        seccomp_path=_resolve(project_root, settings.runtime_seccomp_path),
        data_volume_name=settings.runtime_data_volume_name,
        environment=settings.environment,
        demo_mode=settings.demo_mode,
        bootstrap_image_reference=settings.runtime_image_name,
        docker_binary=settings.docker_binary,
    )
    native_launcher = None
    if settings.runtime_image_digest.startswith("native-runtime@sha256:"):
        native_launcher = NativeRuntimeLauncher(
            python_binary=settings.runtime_python,
            sdk_path=_resolve(project_root, settings.runtime_sdk_path),
            image_digest=settings.runtime_image_digest,
            package_manifest_hash=settings.package_manifest_hash,
            bwrap_binary=settings.bwrap_binary,
        )
    launcher = await select_runtime_launcher(
        launcher_kind=launcher_kind,
        docker_launcher=docker_launcher,
        native_launcher=native_launcher,
    )
    runner = EphemeralRunner(
        workspace_root=_resolve(project_root, settings.runtime_workspace_path),
        launcher=launcher,
    )
    result_pipeline = ResultReviewService(
        repository=repository,
        object_store=object_store,
        ai_client=ai_client if settings.result_interpretation_enabled else None,
    )
    return DurableExecutionWorker(
        repository=repository,
        object_store=object_store,
        runner=runner,
        manifest_signer=ManifestSigner(
            signing_key=settings.manifest_signing_key.get_secret_value().encode("utf-8")
        ),
        worker_id=settings.worker_id,
        lease_seconds=settings.worker_lease_seconds,
        result_pipeline=result_pipeline,
    )
