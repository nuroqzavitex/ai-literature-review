"""Native Linux runtime launcher for VPS deployments without Docker.

The launcher uses bubblewrap user/mount/network namespaces and prlimit. It is
deliberately opt-in; production deployments must explicitly set
``SANDBOX_RUNTIME_LAUNCHER=native``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import shutil
from pathlib import Path

from sandbox_service.execution.docker_launcher import RuntimeUnavailable
from sandbox_service.execution.runner import ExecutionResult, RuntimeSecuritySpec


_NATIVE_DIGEST = re.compile(r"^native-runtime@sha256:([0-9a-f]{64})$")
_LOGGER = logging.getLogger(__name__)


class NativeRuntimeLauncher:
    """Run the analysis interpreter directly under bubblewrap, never a shell."""

    def __init__(
        self,
        *,
        python_binary: str,
        sdk_path: Path,
        image_digest: str,
        package_manifest_hash: str,
        bwrap_binary: str = "bwrap",
    ) -> None:
        match = _NATIVE_DIGEST.fullmatch(image_digest)
        if match is None or match.group(1) != package_manifest_hash:
            raise ValueError(
                "native runtime identity must be native-runtime@sha256:<package manifest hash>"
            )
        configured_python = Path(python_binary)
        if not configured_python.is_absolute():
            located = shutil.which(python_binary)
            configured_python = Path(located) if located else configured_python
        # Do not resolve the venv interpreter symlink: invoking the interpreter
        # through /opt/runtime/bin/python is what activates the sealed venv.
        self._python = configured_python.absolute()
        self._sdk_path = sdk_path.resolve()
        self._bwrap = bwrap_binary
        self._active: dict[str, asyncio.subprocess.Process] = {}
        self._lock = asyncio.Lock()
        self.image_digest = image_digest
        self.package_manifest_hash = package_manifest_hash

    async def ready(self) -> bool:
        return (
            self._python.is_file()
            and os.access(self._python, os.X_OK)
            and (self._sdk_path / "__init__.py").is_file()
            and await self._command_exists(self._bwrap)
            and await self._command_exists("prlimit")
        )

    async def accepts_manifest_image_digest(self, manifest_identity: str) -> bool:
        return manifest_identity == self.image_digest

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
        if not await self.ready():
            raise RuntimeUnavailable("native runtime requires bubblewrap, prlimit, Python and sandbox SDK")
        self._validate_paths(workspace, dataset_path, output_dir, code_path)
        self._validate_security(security)

        command = self._command(
            workspace=workspace,
            dataset_path=dataset_path,
            output_dir=output_dir,
            code_path=code_path,
            random_seed=random_seed,
            security=security,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            _LOGGER.exception("sandbox_native_runtime_start_failed run_id=%s", run_id)
            raise RuntimeUnavailable("native runtime process could not start") from exc

        async with self._lock:
            self._active[run_id] = process
        try:
            stdout, stderr = await process.communicate()
            limit = security.max_log_bytes
            return ExecutionResult(
                exit_code=process.returncode or 0,
                stdout=stdout[:limit].decode("utf-8", errors="replace"),
                stderr=stderr[:limit].decode("utf-8", errors="replace"),
            )
        finally:
            async with self._lock:
                self._active.pop(run_id, None)

    async def cancel(self, *, run_id: str) -> None:
        async with self._lock:
            process = self._active.get(run_id)
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _command(
        self,
        *,
        workspace: Path,
        dataset_path: Path,
        output_dir: Path,
        code_path: Path,
        random_seed: int,
        security: RuntimeSecuritySpec,
    ) -> list[str]:
        del workspace
        dataset_guest = f"/input/dataset{dataset_path.suffix.lower()}"
        runtime_root = self._python.parent.parent
        runtime_bind = ["--ro-bind", runtime_root.as_posix(), "/opt/runtime"]
        guest_python = "/opt/runtime/" + self._python.relative_to(runtime_root).as_posix()
        host_bindings: list[str] = []
        for host_path in (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64")):
            if host_path.exists():
                host_bindings.extend(("--ro-bind", host_path.as_posix(), host_path.as_posix()))
        etc_bindings: list[str] = ["--dir", "/etc"]
        for host_path in (Path("/etc/ld.so.cache"), Path("/etc/fonts"), Path("/etc/localtime")):
            if host_path.exists():
                etc_bindings.extend(("--ro-bind", host_path.as_posix(), host_path.as_posix()))
        return [
            self._bwrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-net",
            "--unshare-ipc",
            "--unshare-uts",
            *host_bindings,
            *etc_bindings,
            "--ro-bind", self._sdk_path.as_posix(), "/opt/sandbox_sdk",
            *runtime_bind,
            "--ro-bind", code_path.parent.as_posix(), "/work",
            "--ro-bind", dataset_path.parent.as_posix(), "/input",
            "--dir", "/workspace",
            "--bind", output_dir.as_posix(), "/workspace/output",
            "--tmpfs", "/tmp",
            "--proc", "/proc",
            "--dev", "/dev",
            "--chdir", "/work",
            "--clearenv",
            "--setenv", "PYTHONPATH", "/opt",
            "--setenv", "SANDBOX_DATASET_PATH", dataset_guest,
            "--setenv", "SANDBOX_OUTPUT_DIR", "/workspace/output",
            "--setenv", "SANDBOX_MAX_OUTPUT_BYTES", str(security.max_output_bytes),
            "--setenv", "SANDBOX_RANDOM_SEED", str(random_seed),
            "--setenv", "PYTHONHASHSEED", str(random_seed),
            "--setenv", "HOME", "/tmp",
            "--setenv", "MPLCONFIGDIR", "/tmp/matplotlib",
            "--setenv", "XDG_CACHE_HOME", "/tmp/cache",
            "--setenv", "OPENBLAS_NUM_THREADS", "1",
            "--setenv", "OMP_NUM_THREADS", "1",
            "--setenv", "MKL_NUM_THREADS", "1",
            "--setenv", "NUMEXPR_NUM_THREADS", "1",
            "--uid", "10001",
            "--gid", "10001",
            "--",
            "prlimit",
            f"--cpu={max(1, int(security.timeout_seconds))}",
            f"--as={security.memory_mb * 1024 * 1024}",
            f"--nproc={security.pid_limit}",
            f"--fsize={security.max_output_bytes}",
            "--",
            guest_python,
            "/work/analysis.py",
        ]

    @staticmethod
    def _validate_paths(
        workspace: Path, dataset_path: Path, output_dir: Path, code_path: Path
    ) -> None:
        root = workspace.resolve()
        for candidate in (dataset_path, output_dir, code_path):
            resolved = candidate.resolve()
            if root != resolved and root not in resolved.parents:
                raise RuntimeUnavailable("native runtime path escaped its staged workspace")
        if not dataset_path.is_file() or not code_path.is_file() or not output_dir.is_dir():
            raise RuntimeUnavailable("native runtime workspace is incomplete")

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
            raise RuntimeUnavailable("native runtime security baseline cannot be disabled")
        if security.cpu_limit > 1 or security.memory_mb > 2048 or security.pid_limit > 32:
            raise RuntimeUnavailable("native runtime limits exceed the approved baseline")

    @staticmethod
    async def _command_exists(command: str) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                command, "--version", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            return await process.wait() == 0
        except OSError:
            return False
