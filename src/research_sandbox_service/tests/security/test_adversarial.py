import asyncio
import json
from pathlib import Path

import pandas as pd
import pytest

from sandbox_sdk import emit_result, emit_table, load_dataset
from sandbox_service.code_policy import CodePolicyChecker, CodePolicyViolation
from sandbox_service.execution import (
    EphemeralRunner,
    ExecutionRequest,
    ExecutionResult,
    RuntimeSecuritySpec,
    docker_security_arguments,
)


@pytest.fixture
def sdk_environment(tmp_path, monkeypatch):
    dataset = tmp_path / "input.csv"
    dataset.write_bytes(b"value\n1\n")
    output = tmp_path / "output"
    monkeypatch.setenv("SANDBOX_DATASET_PATH", str(dataset))
    monkeypatch.setenv("SANDBOX_OUTPUT_DIR", str(output))
    monkeypatch.setenv("SANDBOX_MAX_OUTPUT_BYTES", "1024")
    return dataset, output


def test_sdk_uses_fixed_stage_paths_and_blocks_traversal_and_symlink(sdk_environment, tmp_path, monkeypatch) -> None:
    _, output = sdk_environment
    assert load_dataset().iloc[0, 0] == 1
    emit_result({"schema_version": "analysis_result.v1", "ok": True})
    assert json.loads((output / "analysis_result.json").read_text(encoding="utf-8"))["ok"] is True
    with pytest.raises(ValueError):
        emit_table("../host-leak", pd.DataFrame({"value": [1]}))

    linked_output = tmp_path / "linked-output"
    try:
        linked_output.symlink_to(output, target_is_directory=True)
    except OSError:
        # Windows CI commonly denies the symlink privilege. Simulate the hostile
        # filesystem predicate so the SDK's fail-closed branch is still covered.
        linked_output.mkdir()
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda path: path == linked_output or original_is_symlink(path),
        )
    monkeypatch.setenv("SANDBOX_OUTPUT_DIR", str(linked_output))
    with pytest.raises(RuntimeError):
        emit_result({"schema_version": "analysis_result.v1"})


def test_sdk_bounds_output_and_neutralizes_spreadsheet_formulas(sdk_environment) -> None:
    _, output = sdk_environment
    table = emit_table("formula", pd.DataFrame({"unsafe": ["=cmd()", "-not-a-number"]}))
    rendered = table.read_text(encoding="utf-8")
    assert "'=cmd()" in rendered and "'-not-a-number" in rendered
    with pytest.raises(ValueError):
        emit_result({"large": "x" * 2_000})


class RecordingLauncher:
    def __init__(self, *, delay: float = 0) -> None:
        self.delay = delay
        self.seen_paths: list[Path] = []

    async def run(self, **kwargs) -> ExecutionResult:
        self.seen_paths.append(kwargs["workspace"])
        if self.delay:
            await asyncio.sleep(self.delay)
        assert kwargs["dataset_path"].read_bytes() == b"value\n1\n"
        assert kwargs["output_dir"].is_dir()
        return ExecutionResult(exit_code=0)


@pytest.mark.asyncio
async def test_ephemeral_runner_stages_known_inputs_enforces_timeout_and_cleans_up(tmp_path) -> None:
    root = tmp_path / "workspaces"
    launcher = RecordingLauncher()
    runner = EphemeralRunner(workspace_root=root, launcher=launcher)
    result = await runner.execute(
        ExecutionRequest(
            run_id="run-1",
            dataset_filename="input.csv",
            dataset_bytes=b"value\n1\n",
            code="from sandbox_sdk import emit_result\nemit_result({})",
        )
    )
    assert result.exit_code == 0
    assert launcher.seen_paths and not launcher.seen_paths[0].exists()

    timed_out = await EphemeralRunner(
        workspace_root=root,
        launcher=RecordingLauncher(delay=0.05),
    ).execute(
        ExecutionRequest(
            run_id="run-2",
            dataset_filename="input.csv",
            dataset_bytes=b"value\n1\n",
            code="from sandbox_sdk import emit_result\nemit_result({})",
            security=RuntimeSecuritySpec(timeout_seconds=0),
        )
    )
    assert timed_out.timed_out and not list(root.iterdir())

    with pytest.raises(CodePolicyViolation):
        await runner.execute(
            ExecutionRequest(
                run_id="run-policy-rejected",
                dataset_filename="input.csv",
                dataset_bytes=b"value\n1\n",
                code="from sandbox_sdk import emit_result\nimport os\nemit_result({})",
            )
        )


def test_policy_blocks_host_file_network_process_and_fork_bombs() -> None:
    samples = [
        "from sandbox_sdk import emit_result\nimport socket\nemit_result({})",
        "from sandbox_sdk import emit_result\nimport os\nos.fork()\nemit_result({})",
        "from sandbox_sdk import emit_result\nimport multiprocessing\nemit_result({})",
        "from sandbox_sdk import emit_result\nopen('../../host').read()\nemit_result({})",
    ]
    assert all(not CodePolicyChecker().check(sample).allowed for sample in samples)


def test_docker_security_arguments_lock_down_runtime_mounts(tmp_path) -> None:
    sandbox_root = Path(__file__).resolve().parents[2]
    options = docker_security_arguments(
        security=RuntimeSecuritySpec(),
        data_volume_name="research_sandbox_test_data",
        workspace_subpath="sandbox-run-safe",
        seccomp_path=sandbox_root / "sandbox_runtime" / "seccomp.json",
    )
    assert ["--read-only", "--network", "none"] == options[:3]
    assert "ALL" in options and "no-new-privileges:true" in options
    assert "--pids-limit" in options and "32" in options
    rendered = " ".join(options)
    assert "docker.sock" not in rendered
    assert "type=bind" not in rendered
    assert rendered.count("type=volume") == 3
    assert "volume-subpath=sandbox-run-safe/input" in rendered
    assert "volume-subpath=sandbox-run-safe/output" in rendered
    assert "volume-subpath=sandbox-run-safe/code" in rendered
