"""Opt-in tests that execute the real hardened Docker image.

Run after building the image with:
RUN_DOCKER_SANDBOX_TESTS=1 pytest tests/security/test_runtime_container.py -q
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DOCKER_SANDBOX_TESTS") != "1" or shutil.which("docker") is None,
    reason="real Docker sandbox tests are opt-in",
)


def _run_runtime(*, code: Path, output: Path) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[2]
    dataset = root / "tests" / "fixtures" / "runtime_smoke" / "input.csv"
    seccomp = root / "sandbox_runtime" / "seccomp.json"
    image = os.getenv("SANDBOX_RUNTIME_SMOKE_IMAGE", "research-sandbox-runtime:test")
    return subprocess.run(
        [
            "docker", "run", "--rm", "--read-only", "--network", "none",
            "--cpus", "1", "--memory", "2g", "--pids-limit", "32",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--security-opt", f"seccomp={seccomp}", "--user", "10001:10001",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--mount", f"type=bind,src={dataset},dst=/input/dataset.csv,readonly",
            "--mount", f"type=bind,src={output},dst=/output",
            "--mount", f"type=bind,src={code},dst=/work/analysis.py,readonly",
            "--env", "SANDBOX_DATASET_PATH=/input/dataset.csv",
            "--env", "SANDBOX_OUTPUT_DIR=/output",
            "--env", "SANDBOX_MAX_OUTPUT_BYTES=1048576",
            "--env", "SANDBOX_RANDOM_SEED=42",
            "--env", "PYTHONHASHSEED=42",
            image,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_real_runtime_executes_sdk_flow_under_security_baseline(tmp_path) -> None:
    root = Path(__file__).resolve().parents[2]
    result = _run_runtime(
        code=root / "tests" / "fixtures" / "runtime_smoke" / "analysis.py",
        output=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads((tmp_path / "analysis_result.json").read_text(encoding="utf-8"))
    assert payload["input_row_count"] == payload["analyzed_row_count"] == 3
    assert (tmp_path / "tables" / "summary.csv").is_file()
    chart = tmp_path / "charts" / "summary.png"
    assert chart.is_file()
    assert chart.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_real_runtime_seccomp_blocks_network_syscalls(tmp_path) -> None:
    root = Path(__file__).resolve().parents[2]
    result = _run_runtime(
        code=root / "tests" / "fixtures" / "runtime_smoke" / "network_probe.py",
        output=tmp_path,
    )

    assert result.returncode != 0
    assert not list(tmp_path.rglob("*"))
