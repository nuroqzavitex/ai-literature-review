from pathlib import Path

import pytest

from sandbox_service.code_policy import CodePolicyViolation
from sandbox_service.execution.native_launcher import NativeRuntimeLauncher
from sandbox_service.execution.runner import (
    EphemeralRunner,
    ExecutionRequest,
    RuntimeSecuritySpec,
)
from sandbox_service.worker.factory import select_runtime_launcher


PACKAGE_HASH = "a" * 64
NATIVE_DIGEST = f"native-runtime@sha256:{PACKAGE_HASH}"


class _ReadyLauncher:
    def __init__(self, ready: bool) -> None:
        self._ready = ready

    async def ready(self) -> bool:
        return self._ready


@pytest.mark.asyncio
async def test_auto_launcher_falls_back_to_native_when_docker_is_unavailable() -> None:
    docker = _ReadyLauncher(False)
    native = _ReadyLauncher(True)

    selected = await select_runtime_launcher(
        launcher_kind="auto", docker_launcher=docker, native_launcher=native
    )

    assert selected is native


@pytest.mark.asyncio
async def test_auto_launcher_prefers_docker_when_daemon_is_ready() -> None:
    docker = _ReadyLauncher(True)
    native = _ReadyLauncher(True)

    selected = await select_runtime_launcher(
        launcher_kind="auto", docker_launcher=docker, native_launcher=native
    )

    assert selected is docker


def test_native_command_uses_sealed_venv_sdk_and_network_namespace(tmp_path: Path) -> None:
    python_binary = tmp_path / "runtime" / "venv" / "bin" / "python"
    python_binary.parent.mkdir(parents=True)
    python_binary.write_text("", encoding="utf-8")
    sdk_path = tmp_path / "runtime" / "sandbox_sdk"
    sdk_path.mkdir()
    (sdk_path / "__init__.py").write_text("", encoding="utf-8")
    workspace = tmp_path / "workspace"
    dataset_path = workspace / "input" / "dataset.csv"
    output_dir = workspace / "output"
    code_path = workspace / "code" / "analysis.py"
    dataset_path.parent.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    code_path.parent.mkdir(parents=True)
    dataset_path.write_text("value\n1\n", encoding="utf-8")
    code_path.write_text("pass\n", encoding="utf-8")
    launcher = NativeRuntimeLauncher(
        python_binary=str(python_binary),
        sdk_path=sdk_path,
        image_digest=NATIVE_DIGEST,
        package_manifest_hash=PACKAGE_HASH,
    )

    command = launcher._command(
        workspace=workspace,
        dataset_path=dataset_path,
        output_dir=output_dir,
        code_path=code_path,
        random_seed=42,
        security=RuntimeSecuritySpec(),
    )

    assert "--unshare-net" in command
    assert command[command.index("PYTHONPATH") + 1] == "/opt"
    assert "/opt/runtime/bin/python" in command
    assert command[-1] == "/work/analysis.py"
    assert command[command.index("SANDBOX_DATASET_PATH") + 1] == "/input/dataset.csv"


def test_native_identity_must_match_package_manifest() -> None:
    with pytest.raises(ValueError, match="native runtime identity"):
        NativeRuntimeLauncher(
            python_binary="/runtime/bin/python",
            sdk_path=Path("/runtime/sandbox_sdk"),
            image_digest=f"native-runtime@sha256:{'b' * 64}",
            package_manifest_hash=PACKAGE_HASH,
        )


@pytest.mark.asyncio
async def test_native_mode_keeps_ast_policy_before_subprocess(tmp_path: Path) -> None:
    class _MustNotRun:
        async def run(self, **kwargs):  # pragma: no cover - failure sentinel
            raise AssertionError("native subprocess must not run after an AST rejection")

        async def cancel(self, *, run_id: str) -> None:
            del run_id

    runner = EphemeralRunner(
        workspace_root=tmp_path / "workspaces", launcher=_MustNotRun()
    )

    with pytest.raises(CodePolicyViolation):
        await runner.execute(
            ExecutionRequest(
                run_id="native-policy",
                dataset_filename="dataset.csv",
                dataset_bytes=b"value\n1\n",
                code="import subprocess\n",
            )
        )
