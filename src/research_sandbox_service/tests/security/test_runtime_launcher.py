import asyncio
from pathlib import Path

import pytest

from sandbox_service.execution import (
    ArtifactPolicyViolation,
    DockerCommandResult,
    DockerRuntimeLauncher,
    EphemeralRunner,
    ExecutionRequest,
    ExecutionResult,
    RuntimeSecuritySpec,
)


IMAGE = "sandbox-runtime@sha256:" + "a" * 64
PACKAGES = "b" * 64
VOLUME = "research_sandbox_test_data"


class RecordingDockerExecutor:
    def __init__(
        self,
        run_result: DockerCommandResult | None = None,
        image_result: DockerCommandResult | None = None,
        bootstrap_result: DockerCommandResult | None = None,
    ) -> None:
        self.calls: list[tuple[list[str], int]] = []
        self.run_result = run_result or DockerCommandResult(exit_code=0)
        self.image_result = image_result or DockerCommandResult(exit_code=0)
        self.bootstrap_result = bootstrap_result or self.image_result

    async def execute(
        self, arguments, *, max_output_bytes: int, capture_stdout: bool = False
    ) -> DockerCommandResult:
        command = list(arguments)
        self.calls.append((command, max_output_bytes))
        if command[1:3] == ["image", "inspect"]:
            if command[-1] == "sandbox_runtime:latest":
                return self.bootstrap_result
            return self.image_result
        if command[1:2] == ["run"]:
            return self.run_result
        return DockerCommandResult(exit_code=0)


@pytest.mark.asyncio
async def test_docker_launcher_uses_pinned_image_fixed_mounts_and_no_child_log_content(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    input_dir = workspace / "input"
    output_dir = workspace / "output"
    code_dir = workspace / "code"
    input_dir.mkdir(parents=True)
    output_dir.mkdir()
    code_dir.mkdir()
    dataset = input_dir / "sample.csv"
    code = code_dir / "analysis.py"
    dataset.write_bytes(b"private,value\n1,2\n")
    code.write_text("print('must not enter host logs')", encoding="utf-8")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    executor = RecordingDockerExecutor(
        run_result=DockerCommandResult(
            exit_code=1,
            stdout_bytes=1_000_000,
            stderr_bytes=500,
            truncated=True,
            stderr="docker: Error response from daemon: invalid mount config for type volume",
        )
    )
    launcher = DockerRuntimeLauncher(
        image_digest=IMAGE,
        package_manifest_hash=PACKAGES,
        seccomp_path=seccomp,
        data_volume_name=VOLUME,
        executor=executor,
    )

    result = await launcher.run(
        workspace=workspace,
        dataset_path=dataset,
        output_dir=output_dir,
        code_path=code,
        run_id="run-safe",
        random_seed=17,
        security=RuntimeSecuritySpec(max_log_bytes=2048),
    )

    run_arguments = next(call[0] for call in executor.calls if call[0][1:2] == ["run"])
    rendered = " ".join(run_arguments)
    assert run_arguments[:2] == ["docker", "run"]
    assert run_arguments[-1] == IMAGE
    assert "SANDBOX_DATASET_PATH=/input/dataset.csv" in run_arguments
    assert "SANDBOX_OUTPUT_DIR=/workspace/output" in run_arguments
    assert "SANDBOX_RANDOM_SEED=17" in run_arguments
    assert "PYTHONHASHSEED=17" in run_arguments
    assert "type=bind" not in rendered
    assert f"type=volume,src={VOLUME},dst=/input,readonly" in rendered
    assert f"type=volume,src={VOLUME},dst=/workspace/output" in rendered
    assert "volume-subpath=workspace/input" in rendered
    assert "volume-subpath=workspace/output" in rendered
    assert "volume-subpath=workspace/code" in rendered
    assert "--network none" in rendered and "--cap-drop ALL" in rendered
    assert "docker.sock" not in rendered
    assert "private,value" not in rendered and "must not enter host logs" not in result.stderr
    assert result.stdout == "" and "exceeded the capture limit" in result.stderr
    assert "invalid mount config" in result.stderr
    assert any(call[0][1:3] == ["image", "inspect"] for call in executor.calls)
    assert any(call[0][1:3] == ["rm", "-f"] for call in executor.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("environment", "demo_mode"),
    [("development", False), ("test", True)],
)
async def test_local_runtime_failure_exposes_bounded_python_traceback(
    tmp_path, environment, demo_mode
) -> None:
    workspace = tmp_path / "workspace"
    dataset = workspace / "input" / "sample.csv"
    output_dir = workspace / "output"
    code = workspace / "code" / "analysis.py"
    dataset.parent.mkdir(parents=True)
    output_dir.mkdir()
    code.parent.mkdir()
    dataset.write_text("price per fruit ($)\n1\n", encoding="utf-8")
    code.write_text("raise KeyError('price per fruit ($)')", encoding="utf-8")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    local_image_id = "sha256:" + "c" * 64
    traceback = (
        "Traceback (most recent call last):\n"
        "  File \"/work/analysis.py\", line 1, in <module>\n"
        "KeyError: 'price per fruit ($)'"
    )
    executor = RecordingDockerExecutor(
        run_result=DockerCommandResult(exit_code=1, stderr=traceback),
        bootstrap_result=DockerCommandResult(
            exit_code=0,
            stdout=f'["sandbox_runtime@{local_image_id}"]|{local_image_id}\n',
        ),
    )
    launcher = DockerRuntimeLauncher(
        image_digest=local_image_id,
        package_manifest_hash=PACKAGES,
        seccomp_path=seccomp,
        data_volume_name=VOLUME,
        environment=environment,
        demo_mode=demo_mode,
        bootstrap_image_reference="sandbox_runtime:latest",
        executor=executor,
    )

    result = await launcher.run(
        workspace=workspace,
        dataset_path=dataset,
        output_dir=output_dir,
        code_path=code,
        run_id="run-debug",
        random_seed=17,
        security=RuntimeSecuritySpec(max_log_bytes=32_768),
    )

    assert "Traceback (most recent call last)" in result.stderr
    assert "KeyError: 'price per fruit ($)'" in result.stderr
    assert "suppressed by data-leakage policy" not in result.stderr


def test_docker_launcher_fails_closed_without_pinned_identity(tmp_path) -> None:
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        DockerRuntimeLauncher(
            image_digest="sandbox-runtime:latest",
            package_manifest_hash=PACKAGES,
            seccomp_path=seccomp,
            data_volume_name=VOLUME,
        )
    with pytest.raises(ValueError):
        DockerRuntimeLauncher(
            image_digest=IMAGE,
            package_manifest_hash="not-a-hash",
            seccomp_path=seccomp,
            data_volume_name=VOLUME,
        )
    with pytest.raises(ValueError):
        DockerRuntimeLauncher(
            image_digest=IMAGE,
            package_manifest_hash=PACKAGES,
            seccomp_path=seccomp,
            data_volume_name="../not-a-volume",
        )


def test_docker_launcher_accepts_immutable_local_image_id(tmp_path) -> None:
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    local_image_id = "sha256:" + "c" * 64

    launcher = DockerRuntimeLauncher(
        image_digest=local_image_id,
        package_manifest_hash=PACKAGES,
        seccomp_path=seccomp,
        data_volume_name=VOLUME,
    )

    assert launcher.image_digest == local_image_id


@pytest.mark.asyncio
async def test_docker_launcher_fails_ready_when_pinned_image_is_not_visible(tmp_path) -> None:
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    executor = RecordingDockerExecutor(
        image_result=DockerCommandResult(
            exit_code=1,
            stderr="Error response from daemon: No such image: sha256:missing",
        )
    )
    launcher = DockerRuntimeLauncher(
        image_digest=IMAGE,
        package_manifest_hash=PACKAGES,
        seccomp_path=seccomp,
        data_volume_name=VOLUME,
        executor=executor,
    )

    assert await launcher.ready() is False


@pytest.mark.asyncio
async def test_development_accepts_signed_old_local_id_after_safe_tag_bootstrap(tmp_path) -> None:
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    current_id = "sha256:" + "c" * 64
    previous_control_id = "sha256:" + "d" * 64
    local_buildkit_digest = "sandbox_runtime@sha256:" + "c" * 64
    executor = RecordingDockerExecutor(
        bootstrap_result=DockerCommandResult(
            exit_code=0,
            stdout=f'["{local_buildkit_digest}"]|{current_id}\n',
        )
    )
    launcher = DockerRuntimeLauncher(
        image_digest=current_id,
        package_manifest_hash=PACKAGES,
        seccomp_path=seccomp,
        data_volume_name=VOLUME,
        environment="development",
        bootstrap_image_reference="sandbox_runtime:latest",
        executor=executor,
    )
    runner = EphemeralRunner(workspace_root=tmp_path / "workspaces", launcher=launcher)

    assert await launcher.ready() is True
    assert await runner.accepts_manifest_image_digest(previous_control_id) is True
    assert any(
        call[0][-1] == "sandbox_runtime:latest" for call in executor.calls
    )


@pytest.mark.asyncio
async def test_development_runs_current_bootstrap_image_when_configured_local_id_was_removed(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    dataset = workspace / "input" / "sample.csv"
    output_dir = workspace / "output"
    code = workspace / "code" / "analysis.py"
    dataset.parent.mkdir(parents=True)
    output_dir.mkdir()
    code.parent.mkdir()
    dataset.write_text("value\n1\n", encoding="utf-8")
    code.write_text("from sandbox_sdk import emit_result", encoding="utf-8")
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    stale_id = "sha256:" + "d" * 64
    current_id = "sha256:" + "e" * 64
    executor = RecordingDockerExecutor(
        image_result=DockerCommandResult(exit_code=0),
        bootstrap_result=DockerCommandResult(
            exit_code=0,
            stdout=f'["sandbox_runtime@{current_id}"]|{current_id}\n',
        ),
    )
    launcher = DockerRuntimeLauncher(
        image_digest=stale_id,
        package_manifest_hash=PACKAGES,
        seccomp_path=seccomp,
        data_volume_name=VOLUME,
        environment="development",
        bootstrap_image_reference="sandbox_runtime:latest",
        executor=executor,
    )

    result = await launcher.run(
        workspace=workspace,
        dataset_path=dataset,
        output_dir=output_dir,
        code_path=code,
        run_id="run-after-local-rebuild",
        random_seed=17,
        security=RuntimeSecuritySpec(),
    )

    run_arguments = next(call[0] for call in executor.calls if call[0][1:2] == ["run"])
    assert result.exit_code == 0
    assert run_arguments[-1] == current_id
    assert stale_id not in run_arguments


@pytest.mark.asyncio
async def test_development_does_not_ignore_mismatch_when_repo_digest_exists(tmp_path) -> None:
    seccomp = tmp_path / "seccomp.json"
    seccomp.write_text("{}", encoding="utf-8")
    current_id = "sha256:" + "e" * 64
    current_repo = "registry.example.com/sandbox_runtime@sha256:" + "f" * 64
    stale_id = "sha256:" + "1" * 64
    executor = RecordingDockerExecutor(
        bootstrap_result=DockerCommandResult(
            exit_code=0,
            stdout=f'["{current_repo}"]|{current_id}\n',
        )
    )
    launcher = DockerRuntimeLauncher(
        image_digest=current_id,
        package_manifest_hash=PACKAGES,
        seccomp_path=seccomp,
        data_volume_name=VOLUME,
        demo_mode=True,
        bootstrap_image_reference="sandbox_runtime:latest",
        executor=executor,
    )

    assert await launcher.accepts_manifest_image_digest(stale_id) is False
    assert await launcher.accepts_manifest_image_digest(current_repo) is True


class ArtifactWritingLauncher:
    def __init__(self, relative: str, content: bytes) -> None:
        self.relative = relative
        self.content = content

    async def run(self, **kwargs) -> ExecutionResult:
        target = kwargs["output_dir"] / self.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.content)
        return ExecutionResult(exit_code=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("relative", "content", "limits"),
    [
        ("payload.zip", b"PK\x03\x04", RuntimeSecuritySpec()),
        (
            "tables/oversize.csv",
            b"value\n" + b"x" * 64,
            RuntimeSecuritySpec(max_artifact_bytes=16, max_output_bytes=32),
        ),
        ("charts/not-a-chart.png", b"not-png", RuntimeSecuritySpec()),
    ],
)
async def test_host_rejects_unallowlisted_spoofed_or_oversized_artifacts(
    tmp_path, relative, content, limits
) -> None:
    root = tmp_path / "workspaces"
    runner = EphemeralRunner(
        workspace_root=root, launcher=ArtifactWritingLauncher(relative, content)
    )
    with pytest.raises(ArtifactPolicyViolation):
        await runner.execute(
            ExecutionRequest(
                run_id="run-artifact-policy",
                dataset_filename="input.csv",
                dataset_bytes=b"value\n1\n",
                code="from sandbox_sdk import emit_result\nemit_result({})",
                security=limits,
            )
        )
    assert root.is_dir() and not list(root.iterdir())
