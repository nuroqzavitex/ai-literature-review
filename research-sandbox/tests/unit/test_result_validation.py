import hashlib
import json

import pytest

from sandbox_service.domain.execution import AnalysisArtifact, CreateSandboxRunRequest, SandboxRunStatus
from sandbox_service.domain.errors import OutputValidationFailed
from sandbox_service.domain.results import ResultValidationStatus
from sandbox_service.result_service import ResultReviewService
from tests.fakes import FakeProjectAIClient
from tests.unit.test_execution import VALID_CODE, approve_plan, approved_execution_context, make_execution_service


async def completed_run_with_result(tmp_path, result: dict, *, interpretation_responses=None):
    repository, store, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    execution, _ = make_execution_service(
        repository, FakeProjectAIClient(responses=[{"source_code": VALID_CODE}])
    )
    run = await execution.queue_run(
        project_id="project-a",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        actor_id="user-a",
        idempotency_key="result-run",
        request=CreateSandboxRunRequest(),
    )
    run = await repository.update_sandbox_run(
        run.model_copy(update={"status": SandboxRunStatus.COMPLETED_UNVALIDATED}),
        changed_by="test-worker",
    )
    raw = json.dumps(result, allow_nan=True).encode("utf-8")
    key = f"artifacts/project-a/{run.run_id}/analysis_result.json"
    await store.put_bytes(key=key, data=raw, content_type="application/json")
    artifact = AnalysisArtifact(
        project_id="project-a",
        run_id=run.run_id,
        artifact_type="result",
        filename="analysis_result.json",
        content_hash=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        storage_key=key,
    )
    await repository.save_artifact(artifact)
    ai = FakeProjectAIClient(responses=interpretation_responses or [])
    return ResultReviewService(repository=repository, object_store=store, ai_client=ai), repository, run, ai


def valid_association_result() -> dict:
    return {
        "schema_version": "analysis_result.v1",
        "objective": "associate",
        "method": "Linear regression",
        "input_row_count": 2,
        "analyzed_row_count": 2,
        "preprocessing_applied": [],
        "assumption_checks": [{"name": "residual diagnostics", "passed": True}],
        "metrics": [{"name": "R-squared", "value": 0.8}],
        "statistical_results": [],
        "warnings": [],
        "limitations": ["Association only"],
        "artifact_refs": ["analysis_result.json"],
        "narrative": ["The observed relationship should be interpreted cautiously."],
    }


@pytest.mark.asyncio
async def test_invalid_output_is_blocked_before_interpretation(tmp_path) -> None:
    result = valid_association_result()
    result["metrics"] = [{"name": "R-squared", "value": float("nan")}]
    service, repository, run, ai = await completed_run_with_result(
        tmp_path,
        result,
        interpretation_responses=[{"narrative": [], "numeric_claims": [], "limitations": []}],
    )

    validation = await service.validate_run(project_id="project-a", run_id=run.run_id)

    assert validation.status is ResultValidationStatus.FAILED
    assert (await repository.get_sandbox_run(project_id="project-a", run_id=run.run_id)).status is SandboxRunStatus.VALIDATION_FAILED
    with pytest.raises(OutputValidationFailed):
        await service.interpret_validated(project_id="project-a", run_id=run.run_id)
    assert ai.calls == []


@pytest.mark.asyncio
async def test_validation_scientific_contract_blocks_causal_association(tmp_path) -> None:
    result = valid_association_result()
    result["narrative"] = ["Predictor causes outcome."]
    service, repository, run, _ = await completed_run_with_result(tmp_path, result)

    validation = await service.validate_run(project_id="project-a", run_id=run.run_id)

    assert validation.status is ResultValidationStatus.FAILED
    assert any("causal" in error for error in validation.errors)
    assert (await repository.get_sandbox_run(project_id="project-a", run_id=run.run_id)).status is SandboxRunStatus.VALIDATION_FAILED
