"""Docker launch arguments that enforce the S4 runtime-security baseline."""

from pathlib import Path
import re

from sandbox_service.execution.runner import RuntimeSecuritySpec


_LOCAL_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPOSITORY_DIGEST = re.compile(
    r"^[a-z0-9][a-z0-9._/-]*(?::[a-z0-9._-]+)?@sha256:[0-9a-f]{64}$"
)


def is_pinned_image_identity(value: str) -> bool:
    """Return whether an identity is an immutable local ID or repository digest."""
    return bool(_LOCAL_IMAGE_ID.fullmatch(value) or _REPOSITORY_DIGEST.fullmatch(value))


def runtime_debug_logging_allowed(*, environment: str, demo_mode: bool) -> bool:
    """Allow child tracebacks only in explicitly non-production local modes."""
    return environment.strip().lower() == "development" or demo_mode


def development_image_identity_matches(
    *,
    configured_identity: str,
    manifest_identity: str,
    verified_local_image_id: str | None,
    repository_digests: tuple[str, ...],
    allow_local_fallback: bool,
) -> bool:
    """Compare signed identities without weakening the production digest contract.

    Docker Desktop does not assign ``RepoDigests`` to a locally built image. In a
    development/demo process whose bootstrap tag has already been resolved to a
    valid local image ID, a signed manifest from the sibling process may therefore
    carry a different bootstrap ID after a local rebuild. That compatibility path
    is unavailable as soon as a registry digest exists or outside local mode.
    """
    if not allow_local_fallback:
        return configured_identity == manifest_identity
    if not verified_local_image_id:
        return False
    if repository_digests:
        return manifest_identity in repository_digests
    return is_pinned_image_identity(manifest_identity)


def docker_security_arguments(
    *,
    security: RuntimeSecuritySpec,
    data_volume_name: str,
    workspace_subpath: str,
    seccomp_path: Path,
    dataset_container_path: str = "/input/dataset.csv",
) -> list[str]:
    """Return fixed Docker options backed by one daemon-visible named volume."""
    if dataset_container_path not in {
        "/input/dataset.csv",
        "/input/dataset.xlsx",
        "/input/dataset.parquet",
    }:
        raise ValueError("runtime dataset mount path must use an allowlisted extension")
    arguments = [
        "--read-only",
        "--network", "none",
        "--cpus", str(security.cpu_limit),
        "--memory", f"{security.memory_mb}m",
        "--pids-limit", str(security.pid_limit),
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--security-opt", f"seccomp={seccomp_path.resolve()}",
        "--user", security.user,
        "--tmpfs", f"/tmp:rw,noexec,nosuid,size={security.temp_disk_mb}m",
        "--mount", (
            f"type=volume,src={data_volume_name},dst=/input,readonly,"
            f"volume-subpath={workspace_subpath}/input"
        ),
        "--mount", (
            f"type=volume,src={data_volume_name},dst=/workspace/output,"
            f"volume-subpath={workspace_subpath}/output"
        ),
        "--mount", (
            f"type=volume,src={data_volume_name},dst=/work,readonly,"
            f"volume-subpath={workspace_subpath}/code"
        ),
    ]
    return arguments
