"""Stage a sealed run workspace and delegate execution to an isolated launcher."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import json
import inspect
from pathlib import Path
import shutil
import tempfile
from typing import Protocol

from sandbox_service.code_policy import CodePolicyChecker


@dataclass(frozen=True)
class RuntimeSecuritySpec:
    user: str = "10001:10001"
    read_only_root_filesystem: bool = True
    network_disabled: bool = True
    cap_drop_all: bool = True
    no_new_privileges: bool = True
    cpu_limit: float = 1.0
    memory_mb: int = 2048
    pid_limit: int = 32
    timeout_seconds: int = 120
    temp_disk_mb: int = 1024
    max_output_bytes: int = 64 * 1024 * 1024
    max_artifact_bytes: int = 16 * 1024 * 1024
    max_artifact_count: int = 50
    max_log_bytes: int = 64 * 1024
    kill_grace_seconds: int = 2

    def __post_init__(self) -> None:
        if self.cpu_limit <= 0 or self.memory_mb <= 0 or self.pid_limit <= 0:
            raise ValueError("runtime compute limits must be positive")
        if self.timeout_seconds < 0 or self.temp_disk_mb <= 0:
            raise ValueError("runtime time/disk limits are invalid")
        if min(
            self.max_output_bytes,
            self.max_artifact_bytes,
            self.max_artifact_count,
            self.max_log_bytes,
            self.kill_grace_seconds,
        ) <= 0:
            raise ValueError("runtime output/log limits must be positive")
        if self.max_artifact_bytes > self.max_output_bytes:
            raise ValueError("per-artifact limit cannot exceed the total output limit")


@dataclass(frozen=True)
class ExecutionRequest:
    run_id: str
    dataset_filename: str
    dataset_bytes: bytes
    code: str
    random_seed: int = 42
    security: RuntimeSecuritySpec = RuntimeSecuritySpec()


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    artifacts: tuple["CollectedArtifact", ...] = ()


@dataclass(frozen=True)
class CollectedArtifact:
    artifact_type: str
    filename: str
    content: bytes


class ArtifactPolicyViolation(RuntimeError):
    """The runtime wrote an output that the host refuses to persist."""


class RuntimeLauncher(Protocol):
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
    ) -> ExecutionResult: ...

    async def cancel(self, *, run_id: str) -> None: ...


class EphemeralRunner:
    """Control-plane harness: stage only known bytes and always remove the workspace."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        launcher: RuntimeLauncher,
        policy_checker: CodePolicyChecker | None = None,
    ) -> None:
        self._workspace_root = workspace_root.resolve()
        self._launcher = launcher
        self._policy_checker = policy_checker or CodePolicyChecker()

    @property
    def runtime_image_digest(self) -> str | None:
        return getattr(self._launcher, "image_digest", None)

    @property
    def package_manifest_hash(self) -> str | None:
        return getattr(self._launcher, "package_manifest_hash", None)

    async def accepts_manifest_image_digest(self, manifest_identity: str) -> bool:
        """Delegate environment-aware runtime identity matching to the launcher."""
        checker = getattr(self._launcher, "accepts_manifest_image_digest", None)
        if checker is None:
            configured = self.runtime_image_digest
            return configured is None or configured == manifest_identity
        result = checker(manifest_identity)
        return bool(await result) if inspect.isawaitable(result) else bool(result)

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        self._validate_request(request)
        self._policy_checker.ensure_allowed(request.code)
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix=f"sandbox-run-{request.run_id}-", dir=self._workspace_root))
        try:
            input_dir = workspace / "input"
            output_dir = workspace / "output"
            code_dir = workspace / "code"
            input_dir.mkdir(mode=0o700)
            output_dir.mkdir(mode=0o700)
            code_dir.mkdir(mode=0o700)
            # The runtime consumes a fixed canonical name. The original upload
            # name is used only to validate and retain the allowlisted suffix.
            dataset_path = input_dir / f"dataset{Path(request.dataset_filename).suffix.lower()}"
            code_path = code_dir / "analysis.py"
            dataset_path.write_bytes(request.dataset_bytes)
            code_path.write_text(request.code, encoding="utf-8")
            dataset_path.chmod(0o400)
            code_path.chmod(0o400)
            try:
                result = await asyncio.wait_for(
                    self._launcher.run(
                        workspace=workspace,
                        dataset_path=dataset_path,
                        output_dir=output_dir,
                        code_path=code_path,
                        run_id=request.run_id,
                        random_seed=request.random_seed,
                        security=request.security,
                    ),
                    timeout=request.security.timeout_seconds,
                )
                return replace(
                    result,
                    artifacts=tuple(self._collect_artifacts(output_dir, request.security)),
                )
            except TimeoutError:
                await self.cancel(request.run_id)
                return ExecutionResult(exit_code=124, stderr="Sandbox runtime timed out", timed_out=True)
            except asyncio.CancelledError:
                await self.cancel(request.run_id)
                raise
        finally:
            # Workspace was created directly below the configured root with a known prefix.
            if workspace.parent == self._workspace_root and workspace.name.startswith("sandbox-run-"):
                for path in workspace.rglob("*"):
                    if not path.is_symlink():
                        try:
                            path.chmod(0o700 if path.is_dir() else 0o600)
                        except OSError:
                            pass
                shutil.rmtree(workspace, ignore_errors=True)

    async def cancel(self, run_id: str) -> None:
        """Best-effort cancellation; launchers without active-process support remain testable."""
        cancel = getattr(self._launcher, "cancel", None)
        if cancel is not None:
            await cancel(run_id=run_id)

    async def ready(self) -> bool:
        readiness = getattr(self._launcher, "ready", None)
        if readiness is None:
            return True
        return bool(await readiness())

    @staticmethod
    def _validate_request(request: ExecutionRequest) -> None:
        if not request.run_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in request.run_id):
            raise ValueError("run_id must be a simple identifier")
        if Path(request.dataset_filename).name != request.dataset_filename:
            raise ValueError("dataset filename must not contain a path")
        if not request.dataset_filename.lower().endswith((".csv", ".xlsx", ".parquet")):
            raise ValueError("dataset format is not supported by the runtime")
        if request.random_seed < 0:
            raise ValueError("random_seed must be non-negative")
        limits = request.security
        if min(
            limits.max_output_bytes,
            limits.max_artifact_bytes,
            limits.max_artifact_count,
            limits.max_log_bytes,
        ) <= 0:
            raise ValueError("runtime output limits must be positive")

    @staticmethod
    def _collect_artifacts(
        output_dir: Path, security: RuntimeSecuritySpec
    ) -> list[CollectedArtifact]:
        allowed = {
            Path("analysis_result.json"): "result",
        }
        artifacts: list[CollectedArtifact] = []
        total_size = 0
        file_count = 0
        for path in sorted(output_dir.rglob("*")):
            if path.is_symlink():
                raise ArtifactPolicyViolation("output symlinks are forbidden")
            if not path.is_file():
                continue
            relative = path.relative_to(output_dir)
            if len(relative.parts) > 2:
                raise ArtifactPolicyViolation("nested output paths are forbidden")
            artifact_type = allowed.get(relative)
            if artifact_type is None and relative.parent == Path("tables") and relative.suffix == ".csv":
                artifact_type = "table"
            elif artifact_type is None and relative.parent == Path("charts") and relative.suffix == ".png":
                artifact_type = "chart"
            elif artifact_type is None and relative.parent == Path("diagnostics") and relative.suffix == ".json":
                artifact_type = "diagnostic"
            if artifact_type is None:
                raise ArtifactPolicyViolation(
                    f"output file is not allowlisted: {relative.as_posix()}"
                )
            file_count += 1
            if file_count > security.max_artifact_count:
                raise ArtifactPolicyViolation("artifact count exceeds the host limit")
            size = path.stat().st_size
            if size > security.max_artifact_bytes:
                raise ArtifactPolicyViolation("artifact exceeds the per-file host limit")
            total_size += size
            if total_size > security.max_output_bytes:
                raise ArtifactPolicyViolation("artifacts exceed the total host limit")
            content = path.read_bytes()
            if len(content) != size:
                raise ArtifactPolicyViolation("artifact changed while being collected")
            EphemeralRunner._validate_artifact_content(relative, content)
            artifacts.append(
                CollectedArtifact(
                    artifact_type=artifact_type,
                    filename=relative.as_posix(),
                    content=content,
                )
            )
        return artifacts

    @staticmethod
    def _validate_artifact_content(relative: Path, content: bytes) -> None:
        suffix = relative.suffix.lower()
        if suffix == ".png":
            if not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ArtifactPolicyViolation("chart content does not match PNG format")
            return
        if suffix == ".csv":
            if b"\x00" in content:
                raise ArtifactPolicyViolation("CSV artifact contains binary data")
            try:
                content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ArtifactPolicyViolation("CSV artifact must be UTF-8") from exc
            return
        if suffix == ".json":
            try:
                json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ArtifactPolicyViolation("JSON artifact is malformed") from exc
