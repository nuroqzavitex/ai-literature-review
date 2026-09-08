"""Run one real Docker-out-of-Docker analysis without database side effects."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sandbox_service.adapters.development import DeterministicProjectAIClient
from sandbox_service.config import SandboxSettings
from sandbox_service.execution import (
    DockerRuntimeLauncher,
    EphemeralRunner,
    ExecutionRequest,
    RuntimeSecuritySpec,
)


async def main() -> None:
    settings = SandboxSettings()
    project_root = Path(__file__).resolve().parents[1]
    seccomp_path = settings.runtime_seccomp_path
    if not seccomp_path.is_absolute():
        seccomp_path = project_root / seccomp_path
    workspace_root = settings.runtime_workspace_path
    if not workspace_root.is_absolute():
        workspace_root = project_root / workspace_root
    runtime_metadata = Path("/run/sandbox-runtime")
    image_digest = settings.runtime_image_digest
    package_manifest_hash = settings.package_manifest_hash
    if (runtime_metadata / "image-ref").is_file():
        image_digest = (runtime_metadata / "image-ref").read_text(
            encoding="utf-8"
        ).strip()
    if (runtime_metadata / "package-manifest-hash").is_file():
        package_manifest_hash = (runtime_metadata / "package-manifest-hash").read_text(
            encoding="utf-8"
        ).strip()
    source = DeterministicProjectAIClient._analysis_source(
        {
            "objective": "describe",
            "method": "deterministic smoke summary",
            "outcome_columns": ["price per fruit ($)"],
            "predictor_columns": ["count sold", "fruit name"],
        }
    )
    launcher = DockerRuntimeLauncher(
        image_digest=image_digest,
        package_manifest_hash=package_manifest_hash,
        seccomp_path=seccomp_path,
        data_volume_name=settings.runtime_data_volume_name,
        environment=settings.environment,
        demo_mode=settings.demo_mode,
        bootstrap_image_reference=settings.runtime_image_name,
        docker_binary=settings.docker_binary,
    )
    runner = EphemeralRunner(workspace_root=workspace_root, launcher=launcher)
    result = await runner.execute(
        ExecutionRequest(
            run_id="runtime-smoke-special-columns",
            dataset_filename="fruit sales.csv",
            dataset_bytes=(
                b"price per fruit ($),count sold,fruit name\n"
                b"1.25,10,apple\n2.50,4,dragon fruit\n"
            ),
            code=source,
            random_seed=17,
            security=RuntimeSecuritySpec(timeout_seconds=30),
        )
    )
    artifact_names = sorted(item.filename for item in result.artifacts)
    if result.exit_code != 0:
        raise RuntimeError(f"runtime smoke failed: {result.stderr}")
    expected = ["analysis_result.json", "tables/summary.csv"]
    if artifact_names != expected:
        raise RuntimeError(
            f"runtime smoke produced {artifact_names!r}; expected {expected!r}"
        )
    print(f"runtime smoke passed: exit_code=0 artifacts={artifact_names}")


if __name__ == "__main__":
    asyncio.run(main())
