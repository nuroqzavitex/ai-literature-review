"""Dedicated Docker CLI adapter for ephemeral analysis containers.

The adapter never invokes a shell, requires a pinned image identity, and transports
staged files through a daemon-visible named volume. Child output is consumed with a
strict bound; only allowlisted Docker infrastructure diagnostics reach worker logs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Protocol, Sequence

from sandbox_service.execution.docker_security import (
    development_image_identity_matches,
    docker_security_arguments,
    is_pinned_image_identity,
    runtime_debug_logging_allowed,
)
from sandbox_service.execution.runner import ExecutionResult, RuntimeSecuritySpec


_VOLUME_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,254}$")
_IMAGE_TAG = re.compile(r"^[a-z0-9][a-z0-9._/-]*(?::[a-z0-9._-]+)?$")
_LOGGER = logging.getLogger(__name__)


class RuntimeUnavailable(RuntimeError):
    """The isolated runtime cannot be reached or is not safely configured."""


@dataclass(frozen=True)
class DockerCommandResult:
    exit_code: int
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    truncated: bool = False
    stdout: str = ""
    stderr: str = ""


class DockerCommandExecutor(Protocol):
    async def execute(
        self,
        arguments: Sequence[str],
        *,
        max_output_bytes: int,
        capture_stdout: bool = False,
    ) -> DockerCommandResult: ...


class AsyncioDockerCommandExecutor:
    """Run Docker without a shell while consuming logs with a strict memory bound."""

    async def execute(
        self,
        arguments: Sequence[str],
        *,
        max_output_bytes: int,
        capture_stdout: bool = False,
    ) -> DockerCommandResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise RuntimeUnavailable("Docker CLI is unavailable") from exc

        assert process.stdout is not None and process.stderr is not None
        per_stream_limit = max(1, max_output_bytes // 2)
        stdout_task = asyncio.create_task(
            self._consume_bounded(
                process.stdout, per_stream_limit, capture=capture_stdout
            )
        )
        stderr_task = asyncio.create_task(
            self._consume_bounded(process.stderr, per_stream_limit, capture=True)
        )
        try:
            exit_code = await process.wait()
            stdout_bytes, stdout_truncated, retained_stdout = await stdout_task
            stderr_bytes, stderr_truncated, retained_stderr = await stderr_task
            return DockerCommandResult(
                exit_code=exit_code,
                stdout_bytes=stdout_bytes,
                stderr_bytes=stderr_bytes,
                truncated=stdout_truncated or stderr_truncated,
                stdout=retained_stdout.decode("utf-8", errors="replace"),
                stderr=retained_stderr.decode("utf-8", errors="replace"),
            )
        except asyncio.CancelledError:
            if process.returncode is None:
                process.kill()
                await process.wait()
            for task in (stdout_task, stderr_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise

    @staticmethod
    async def _consume_bounded(
        stream: asyncio.StreamReader, retain_limit: int, *, capture: bool
    ) -> tuple[int, bool, bytes]:
        total = 0
        retained = bytearray()
        while chunk := await stream.read(8192):
            total += len(chunk)
            if capture and len(retained) < retain_limit:
                retained.extend(chunk[: retain_limit - len(retained)])
        return total, total > retain_limit, bytes(retained)


class DockerRuntimeLauncher:
    """Launch one immutable runtime container per run and always remove it."""

    def __init__(
        self,
        *,
        image_digest: str,
        package_manifest_hash: str,
        seccomp_path: Path,
        data_volume_name: str,
        environment: str = "production",
        demo_mode: bool = False,
        bootstrap_image_reference: str | None = None,
        docker_binary: str = "docker",
        executor: DockerCommandExecutor | None = None,
    ) -> None:
        if not is_pinned_image_identity(image_digest):
            raise ValueError("runtime image must be pinned by sha256 digest")
        if not re.fullmatch(r"[0-9a-f]{64}", package_manifest_hash):
            raise ValueError("package manifest hash must be a sha256 digest")
        if not _VOLUME_NAME.fullmatch(data_volume_name):
            raise ValueError("runtime data volume name is invalid")
        allow_local_fallback = runtime_debug_logging_allowed(
            environment=environment, demo_mode=demo_mode
        )
        if bootstrap_image_reference is not None and not _IMAGE_TAG.fullmatch(
            bootstrap_image_reference
        ):
            raise ValueError("runtime bootstrap image reference must be a safe tag")
        if allow_local_fallback and bootstrap_image_reference is None:
            raise ValueError("local runtime identity fallback requires a bootstrap image tag")
        self._image_digest = image_digest
        self._package_manifest_hash = package_manifest_hash
        self._seccomp_path = seccomp_path.resolve()
        self._data_volume_name = data_volume_name
        self._allow_local_identity_fallback = allow_local_fallback
        self._expose_child_stderr = allow_local_fallback
        self._bootstrap_image_reference = bootstrap_image_reference
        self._verified_local_image_id: str | None = None
        self._repository_digests: tuple[str, ...] = ()
        self._execution_image_identity = image_digest
        self._docker_binary = docker_binary
        self._executor = executor or AsyncioDockerCommandExecutor()
        self._active: dict[str, str] = {}
        self._active_lock = asyncio.Lock()

    @property
    def image_digest(self) -> str:
        return self._image_digest

    @property
    def package_manifest_hash(self) -> str:
        return self._package_manifest_hash

    async def accepts_manifest_image_digest(self, manifest_identity: str) -> bool:
        """Compare a signed manifest identity against the verified runtime image."""
        if not self._allow_local_identity_fallback:
            return self._image_digest == manifest_identity
        await self._verify_bootstrap_image(4096)
        accepted = development_image_identity_matches(
            configured_identity=self._image_digest,
            manifest_identity=manifest_identity,
            verified_local_image_id=self._verified_local_image_id,
            repository_digests=self._repository_digests,
            allow_local_fallback=True,
        )
        if accepted:
            _LOGGER.warning(
                "sandbox_runtime_local_identity_compatibility manifest_image=%s "
                "verified_local_image=%s bootstrap_tag=%s",
                manifest_identity,
                self._verified_local_image_id,
                self._bootstrap_image_reference,
            )
        return accepted

    async def run(
        self,
        *,
        workspace: Path,
        dataset_path: Path,
        output_dir: Path,
        code_path: Path,
        run_id: str,
        random_seed: int,
        security: RuntimeSecuritySpec,
    ) -> ExecutionResult:
        self._validate_paths(workspace, dataset_path, output_dir, code_path)
        self._validate_security(security)
        if not self._seccomp_path.is_file():
            raise RuntimeUnavailable("seccomp profile is unavailable")
        container_name = self._container_name(run_id, workspace)
        dataset_container_path = f"/input/dataset{dataset_path.suffix.lower()}"
        workspace_subpath = workspace.name
        async with self._active_lock:
            if run_id in self._active:
                raise RuntimeUnavailable("a runtime is already active for this run")
            self._active[run_id] = container_name

        try:
            await self._ensure_image_available(security.max_log_bytes)
            arguments = [
                self._docker_binary,
                "run",
                "--rm",
                "--name",
                container_name,
                "--label",
                "research-sandbox.managed=true",
                "--label",
                f"research-sandbox.run-id={run_id}",
                *docker_security_arguments(
                    security=security,
                    data_volume_name=self._data_volume_name,
                    workspace_subpath=workspace_subpath,
                    seccomp_path=self._seccomp_path,
                    dataset_container_path=dataset_container_path,
                ),
                "--env",
                f"SANDBOX_DATASET_PATH={dataset_container_path}",
                "--env",
                "SANDBOX_OUTPUT_DIR=/workspace/output",
                "--env",
                f"SANDBOX_MAX_OUTPUT_BYTES={security.max_output_bytes}",
                "--env",
                f"SANDBOX_RANDOM_SEED={random_seed}",
                "--env",
                f"PYTHONHASHSEED={random_seed}",
                "--workdir",
                "/work",
                self._execution_image_identity,
            ]
            outcome = await self._executor.execute(
                arguments, max_output_bytes=security.max_log_bytes
            )
            # Production exposes only allowlisted daemon diagnostics. Local
            # development/demo mode intentionally exposes the bounded child
            # traceback so runtime failures can be diagnosed.
            stderr = "" if outcome.exit_code == 0 else f"Sandbox runtime exited with code {outcome.exit_code}"
            if outcome.truncated:
                stderr = f"{stderr}; runtime logs exceeded the capture limit".lstrip("; ")
            if outcome.exit_code != 0:
                diagnostic = self._runtime_diagnostic(outcome.stderr)
                _LOGGER.error(
                    "sandbox_runtime_docker_error run_id=%s image=%s volume=%s "
                    "exit_code=%s stderr=%s",
                    run_id,
                    self._image_digest,
                    self._data_volume_name,
                    outcome.exit_code,
                    diagnostic,
                )
                if diagnostic:
                    stderr = f"{stderr}; {diagnostic}"
            return ExecutionResult(exit_code=outcome.exit_code, stderr=stderr)
        except asyncio.CancelledError:
            await self.cancel(run_id=run_id)
            raise
        except Exception as exc:
            _LOGGER.exception(
                "sandbox_runtime_launcher_exception run_id=%s image=%s volume=%s",
                run_id,
                self._image_digest,
                self._data_volume_name,
            )
            if isinstance(exc, RuntimeUnavailable):
                raise
            raise RuntimeUnavailable("Docker runtime launch failed") from exc
        finally:
            await self._remove(container_name, security.max_log_bytes)
            async with self._active_lock:
                self._active.pop(run_id, None)

    async def cancel(self, *, run_id: str) -> None:
        async with self._active_lock:
            container_name = self._active.get(run_id)
        if container_name is None:
            return
        await self._control((self._docker_binary, "kill", container_name))
        await self._control((self._docker_binary, "rm", "-f", container_name))

    async def ready(self) -> bool:
        try:
            result = await self._executor.execute(
                (self._docker_binary, "info", "--format", "{{.ServerVersion}}"),
                max_output_bytes=1024,
            )
            if result.exit_code != 0:
                return False
            await self._ensure_image_available(4096)
        except RuntimeUnavailable:
            return False
        return self._seccomp_path.is_file()

    async def _ensure_image_available(self, max_output_bytes: int) -> None:
        if self._allow_local_identity_fallback:
            # The compose bootstrap metadata is captured when the worker starts.
            # Docker Desktop may replace that local image ID during a later
            # rebuild while leaving the long-running worker alive. Resolve the
            # already-validated bootstrap tag on every readiness/run boundary so
            # development jobs use the current immutable local ID.
            await self._verify_bootstrap_image(max_output_bytes)
        result = await self._executor.execute(
            (
                self._docker_binary,
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                self._execution_image_identity,
            ),
            max_output_bytes=max_output_bytes,
        )
        if result.exit_code != 0:
            diagnostic = self._runtime_diagnostic(result.stderr)
            _LOGGER.error(
                "sandbox_runtime_image_unavailable image=%s exit_code=%s stderr=%s",
                self._execution_image_identity,
                result.exit_code,
                diagnostic,
            )
            raise RuntimeUnavailable(
                f"runtime image is unavailable to the Docker daemon: {diagnostic or 'inspect failed'}"
            )

    async def _verify_bootstrap_image(self, max_output_bytes: int) -> None:
        reference = self._bootstrap_image_reference
        if reference is None:
            raise RuntimeUnavailable("runtime bootstrap image tag is not configured")
        result = await self._executor.execute(
            (
                self._docker_binary,
                "image",
                "inspect",
                "--format",
                "{{json .RepoDigests}}|{{.Id}}",
                reference,
            ),
            max_output_bytes=max_output_bytes,
            capture_stdout=True,
        )
        if result.exit_code != 0:
            diagnostic = self._runtime_diagnostic(result.stderr)
            raise RuntimeUnavailable(
                f"runtime bootstrap tag is unavailable: {diagnostic or 'inspect failed'}"
            )
        repo_json, separator, local_image_id = result.stdout.strip().rpartition("|")
        if not separator or not re.fullmatch(r"sha256:[0-9a-f]{64}", local_image_id):
            raise RuntimeUnavailable("runtime bootstrap image identity is malformed")
        try:
            decoded = json.loads(repo_json)
        except json.JSONDecodeError as exc:
            raise RuntimeUnavailable("runtime RepoDigests metadata is malformed") from exc
        if decoded is None:
            all_repo_digests: tuple[str, ...] = ()
        elif isinstance(decoded, list) and all(
            isinstance(item, str) and is_pinned_image_identity(item) for item in decoded
        ):
            all_repo_digests = tuple(decoded)
        else:
            raise RuntimeUnavailable("runtime RepoDigests metadata is malformed")
        # BuildKit/Docker Desktop may synthesize ``sandbox_runtime@sha256:...``
        # for a local-only tag. It is not evidence of a remote registry identity.
        remote_repo_digests = tuple(
            item
            for item in all_repo_digests
            if not self._is_local_bootstrap_repo_digest(item, reference)
        )
        if self._image_digest.startswith("sha256:"):
            if local_image_id != self._image_digest:
                if remote_repo_digests:
                    raise RuntimeUnavailable(
                        "runtime bootstrap tag no longer resolves to the configured local image ID"
                    )
                _LOGGER.warning(
                    "sandbox_runtime_local_image_rotated configured_image=%s "
                    "verified_local_image=%s bootstrap_tag=%s",
                    self._image_digest,
                    local_image_id,
                    reference,
                )
            self._execution_image_identity = local_image_id
        elif all_repo_digests and self._image_digest not in all_repo_digests:
            raise RuntimeUnavailable(
                "runtime bootstrap tag does not resolve to the configured repository digest"
            )
        else:
            self._execution_image_identity = self._image_digest
        self._verified_local_image_id = local_image_id
        self._repository_digests = remote_repo_digests

    @staticmethod
    def _is_local_bootstrap_repo_digest(digest: str, bootstrap_tag: str) -> bool:
        digest_repository = digest.split("@", 1)[0]
        slash = bootstrap_tag.rfind("/")
        colon = bootstrap_tag.rfind(":")
        bootstrap_repository = (
            bootstrap_tag[:colon] if colon > slash else bootstrap_tag
        )
        first_component = bootstrap_repository.split("/", 1)[0]
        explicitly_remote = (
            "." in first_component
            or ":" in first_component
            or first_component == "localhost"
        )
        return digest_repository == bootstrap_repository and not explicitly_remote

    async def _remove(self, container_name: str, max_output_bytes: int) -> None:
        await self._control(
            (self._docker_binary, "rm", "-f", container_name),
            max_output_bytes=max_output_bytes,
        )

    async def _control(
        self, arguments: Sequence[str], *, max_output_bytes: int = 4096
    ) -> None:
        try:
            await self._executor.execute(arguments, max_output_bytes=max_output_bytes)
        except RuntimeUnavailable:
            # Cleanup is best effort; the worker still records the run failure.
            return

    @staticmethod
    def _container_name(run_id: str, workspace: Path) -> str:
        suffix = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()[:12]
        return f"research-sandbox-{run_id}-{suffix}"[:63]

    @staticmethod
    def _validate_paths(
        workspace: Path, dataset_path: Path, output_dir: Path, code_path: Path
    ) -> None:
        root = workspace.resolve()
        for candidate in (dataset_path, output_dir, code_path):
            resolved = candidate.resolve()
            if root != resolved and root not in resolved.parents:
                raise RuntimeUnavailable("runtime mount escaped its staged workspace")
        if not dataset_path.is_file() or not code_path.is_file() or not output_dir.is_dir():
            raise RuntimeUnavailable("runtime workspace is incomplete")

    @staticmethod
    def _validate_security(security: RuntimeSecuritySpec) -> None:
        if not all(
            (
                security.read_only_root_filesystem,
                security.network_disabled,
                security.cap_drop_all,
                security.no_new_privileges,
            )
        ):
            raise RuntimeUnavailable("runtime security baseline cannot be disabled")
        if security.cpu_limit > 1 or security.memory_mb > 2048 or security.pid_limit > 32:
            raise RuntimeUnavailable("runtime resource limits exceed the approved baseline")

    def _runtime_diagnostic(self, stderr: str) -> str:
        """Expose bounded child tracebacks locally; fail closed in production."""
        cleaned = stderr.replace("\x00", "").strip()
        if self._expose_child_stderr:
            return cleaned
        compact = " ".join(cleaned.split())[:4096]
        infrastructure_markers = (
            "docker:",
            "daemon",
            "mount",
            "volume",
            "image",
            "seccomp",
            "permission denied",
            "no such file or directory",
            "invalid reference format",
            "pull access denied",
        )
        if compact and any(marker in compact.lower() for marker in infrastructure_markers):
            return compact
        return "runtime child stderr suppressed by data-leakage policy" if compact else ""
