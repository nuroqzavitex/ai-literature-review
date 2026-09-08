from datetime import UTC, datetime, timedelta

import pytest
from sandbox_service.analysis_service import AnalysisPlanService
from sandbox_service.code_generation_service import CodeGenerationService
from sandbox_service.dataset_service import DatasetService
from sandbox_service.domain.analysis_plans import (
    CreateAnalysisPlanRequest,
    CreateAnalysisQuestionRequest,
    ReviewAnalysisPlanRequest,
)
from sandbox_service.domain.datasets import DatasetClassification
from sandbox_service.domain.errors import AnalysisPlanNotApproved, CodePolicyRejected
from sandbox_service.domain.execution import CreateSandboxRunRequest, SandboxRunStatus
from sandbox_service.execution.manifest import ManifestSigner, ManifestVerificationError
from sandbox_service.execution.runner import EphemeralRunner, ExecutionResult
from sandbox_service.execution_service import ExecutionService
from sandbox_service.frontend_service import FrontendQueryService
from sandbox_service.repositories.memory import InMemorySandboxSessionRepository
from sandbox_service.storage import LocalObjectStore
from sandbox_service.worker import DurableExecutionWorker
from tests.fakes import FakeProjectAIClient

VALID_CODE = """
import matplotlib.pyplot as plt
from sandbox_sdk import emit_chart, emit_result, load_dataset

df = load_dataset()
figure, axis = plt.subplots()
axis.plot([0], [0])
emit_chart("analysis", figure)
plt.close(figure)
emit_result({"schema_version": "analysis_result.v1", "input_row_count": len(df), "artifact_refs": ["charts/analysis.png"]})
"""


class SuccessfulLauncher:
    def __init__(self, *, write_artifact: bool = False) -> None:
        self.calls = 0
        self.write_artifact = write_artifact

    async def run(self, **kwargs) -> ExecutionResult:
        self.calls += 1
        assert kwargs["dataset_path"].is_file()
        assert kwargs["code_path"].is_file()
        if self.write_artifact:
            (kwargs["output_dir"] / "tables").mkdir()
            (kwargs["output_dir"] / "tables" / "summary.csv").write_text("metric,value\nn,2\n", encoding="utf-8")
        return ExecutionResult(exit_code=0)


async def approved_execution_context(tmp_path):
    repository = InMemorySandboxSessionRepository()
    store = LocalObjectStore(tmp_path / "objects")
    datasets = DatasetService(repository=repository, object_store=store)
    uploaded = await datasets.upload(
        project_id="project-a",
        actor_id="user-a",
        filename="run.csv",
        declared_media_type="text/csv",
        classification=DatasetClassification.NON_SENSITIVE,
        data=b"outcome,predictor\n1,2\n2,3\n",
    )
    await datasets.profile(project_id="project-a", dataset_id=uploaded.dataset_id)
    plan_ai = FakeProjectAIClient(
        responses=[
            {
                "method": "Linear regression",
                "method_rationale": "A numeric outcome and predictor were selected.",
                "preprocessing_steps": [],
                "assumption_checks": ["residual diagnostics"],
                "evaluation_metrics": ["R-squared"],
                "limitations": ["Association only"],
            }
        ]
    )
    plans = AnalysisPlanService(repository=repository, ai_client=plan_ai)
    question = await plans.clarify_question(
        project_id="project-a",
        dataset_id=uploaded.dataset_id,
        actor_id="user-a",
        request=CreateAnalysisQuestionRequest(
            objective="associate",
            research_question="Is predictor associated with outcome?",
            outcome_columns=["outcome"],
            predictor_columns=["predictor"],
        ),
    )
    plan = await plans.create_plan(
        project_id="project-a",
        dataset_id=uploaded.dataset_id,
        actor_id="user-a",
        request=CreateAnalysisPlanRequest(question_id=question.question_id),
    )
    return repository, store, uploaded, plans, plan


async def approve_plan(plans, plan):
    await plans.review_plan(
        project_id="project-a",
        plan_id=plan.plan_id,
        version=plan.version,
        reviewer_id="reviewer-a",
        idempotency_key=f"{plan.plan_id}-review",
        request=ReviewAnalysisPlanRequest(decision="in_review"),
    )
    return await plans.review_plan(
        project_id="project-a",
        plan_id=plan.plan_id,
        version=plan.version,
        reviewer_id="reviewer-a",
        idempotency_key=f"{plan.plan_id}-approve",
        request=ReviewAnalysisPlanRequest(decision="approved"),
    )


def make_execution_service(repository, code_ai):
    signer = ManifestSigner(signing_key=b"test-manifest-signing-key-must-be-32-bytes")
    code_generation = CodeGenerationService(repository=repository, ai_client=code_ai)
    return ExecutionService(
        repository=repository,
        code_generation=code_generation,
        manifest_signer=signer,
        image_digest="sandbox-runtime@sha256:" + "1" * 64,
        package_manifest_hash="2" * 64,
    ), signer


@pytest.mark.asyncio
async def test_unapproved_plan_cannot_create_run(tmp_path) -> None:
    repository, _, _, _, plan = await approved_execution_context(tmp_path)
    service, _ = make_execution_service(repository, FakeProjectAIClient(responses=[]))

    with pytest.raises(AnalysisPlanNotApproved):
        await service.queue_run(
            project_id="project-a",
            plan_id=plan.plan_id,
            plan_version=plan.version,
            actor_id="user-a",
            idempotency_key="run-unapproved",
            request=CreateSandboxRunRequest(),
        )


@pytest.mark.asyncio
async def test_code_generation_is_policy_checked_and_manifest_is_signed(tmp_path) -> None:
    repository, _, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    code_ai = FakeProjectAIClient(responses=[{"source_code": VALID_CODE}])
    service, signer = make_execution_service(repository, code_ai)

    run = await service.queue_run(
        project_id="project-a",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        actor_id="user-a",
        idempotency_key="run-signed",
        request=CreateSandboxRunRequest(random_seed=7),
    )

    signer.verify(run.manifest)
    assert run.status is SandboxRunStatus.QUEUED
    assert run.manifest.plan_hash == plan.plan_hash
    assert run.manifest.random_seed == 7
    assert code_ai.calls[0]["prompt_version"] == "analysis.code_generation.v1"
    assert "outcome,predictor" not in str(code_ai.calls[0]["input_payload"])
    with pytest.raises(ManifestVerificationError):
        signer.verify(run.manifest.model_copy(update={"plan_hash": "tampered"}))


@pytest.mark.asyncio
async def test_code_generation_revises_incomplete_p_value_result_before_queueing(tmp_path) -> None:
    repository, _, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    incomplete = """
import matplotlib.pyplot as plt
from sandbox_sdk import emit_chart, emit_result, load_dataset

df = load_dataset()
figure, axis = plt.subplots()
axis.plot([0], [0])
emit_chart("analysis", figure)
plt.close(figure)
emit_result({
    "input_row_count": len(df),
    "analyzed_row_count": len(df),
    "statistical_results": [{"name": "slope", "p_value": 0.02}],
})
"""
    corrected = """
import matplotlib.pyplot as plt
from sandbox_sdk import emit_chart, emit_result, load_dataset

df = load_dataset()
figure, axis = plt.subplots()
axis.plot([0], [0])
emit_chart("analysis", figure)
plt.close(figure)
emit_result({
    "input_row_count": len(df),
    "analyzed_row_count": len(df),
    "statistical_results": [{
        "name": "slope",
        "p_value": 0.02,
        "effect_size": 0.4,
        "confidence_interval": [0.1, 0.7],
    }],
})
"""
    code_ai = FakeProjectAIClient(
        responses=[{"source_code": incomplete}, {"source_code": corrected}]
    )
    service, _ = make_execution_service(repository, code_ai)

    run = await service.queue_run(
        project_id="project-a",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        actor_id="user-a",
        idempotency_key="run-auto-revised",
        request=CreateSandboxRunRequest(),
    )
    code = await repository.get_analysis_code(
        project_id="project-a", code_version_id=run.code_version_id
    )

    assert code is not None
    assert code.prompt_version == "analysis.code_revision.v1"
    assert code.revision_count == 1
    assert "confidence_interval" in code.source_code
    assert [call["prompt_version"] for call in code_ai.calls] == [
        "analysis.code_generation.v1",
        "analysis.code_revision.v1",
    ]
    assert "p_value" in code_ai.calls[1]["input_payload"]["recoverable_error"]


@pytest.mark.asyncio
async def test_code_generation_revises_scatter_only_association_chart(tmp_path) -> None:
    repository, _, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    scatter_only = """
import matplotlib.pyplot as plt
from sandbox_sdk import emit_chart, emit_result, load_dataset

df = load_dataset()
figure, axis = plt.subplots()
axis.scatter(df["predictor"], df["outcome"], label="Observed data")
emit_chart("analysis", figure)
plt.close(figure)
emit_result({"input_row_count": len(df), "analyzed_row_count": len(df)})
"""
    corrected = """
import matplotlib.pyplot as plt
import numpy as np
from sandbox_sdk import emit_chart, emit_result, load_dataset

df = load_dataset()
figure, axis = plt.subplots()
axis.scatter(df["predictor"], df["outcome"], label="Observed data")
coefficients = np.polyfit(df["predictor"], df["outcome"], 1)
trend_x = np.sort(df["predictor"].to_numpy())
trend_y = coefficients[0] * trend_x + coefficients[1]
axis.plot(trend_x, trend_y, label="Fitted trend")
axis.legend()
emit_chart("analysis", figure)
plt.close(figure)
emit_result({"input_row_count": len(df), "analyzed_row_count": len(df)})
"""
    code_ai = FakeProjectAIClient(
        responses=[{"source_code": scatter_only}, {"source_code": corrected}]
    )
    service, _ = make_execution_service(repository, code_ai)

    run = await service.queue_run(
        project_id="project-a",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        actor_id="user-a",
        idempotency_key="run-auto-trend-revision",
        request=CreateSandboxRunRequest(),
    )
    code = await repository.get_analysis_code(
        project_id="project-a", code_version_id=run.code_version_id
    )

    assert code is not None
    assert code.prompt_version == "analysis.code_revision.v1"
    assert "axis.plot(trend_x, trend_y" in code.source_code
    assert "fitted trend/regression line" in code_ai.calls[1]["input_payload"]["recoverable_error"]


@pytest.mark.asyncio
async def test_code_generation_revises_erroneous_unscaling_prediction(tmp_path) -> None:
    repository, _, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    erroneous_unscaling = """
import matplotlib.pyplot as plt
import statsmodels.api as sm
from sandbox_sdk import emit_chart, emit_result, load_dataset

df = load_dataset()
X = sm.add_constant(df[["predictor"]], has_constant="add")
y = df["outcome"]
model = sm.OLS(y, X).fit()
line_y_scaled = model.predict(X)
line_y = line_y_scaled * df["outcome"].std() + df["outcome"].mean()

figure, axis = plt.subplots()
axis.scatter(df["predictor"], df["outcome"], label="Observed data")
axis.plot(df["predictor"], line_y, label="Fitted line")
axis.legend()
emit_chart("analysis", figure)
plt.close(figure)
emit_result({"input_row_count": len(df), "analyzed_row_count": len(df)})
"""
    corrected = """
import matplotlib.pyplot as plt
import statsmodels.api as sm
from sandbox_sdk import emit_chart, emit_result, load_dataset

df = load_dataset()
X = sm.add_constant(df[["predictor"]], has_constant="add")
y = df["outcome"]
model = sm.OLS(y, X).fit()
line_y = model.predict(X)

figure, axis = plt.subplots()
axis.scatter(df["predictor"], df["outcome"], label="Observed data")
axis.plot(df["predictor"], line_y, label="Fitted line")
axis.legend()
emit_chart("analysis", figure)
plt.close(figure)
emit_result({"input_row_count": len(df), "analyzed_row_count": len(df)})
"""
    code_ai = FakeProjectAIClient(
        responses=[{"source_code": erroneous_unscaling}, {"source_code": corrected}]
    )
    service, _ = make_execution_service(repository, code_ai)

    run = await service.queue_run(
        project_id="project-a",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        actor_id="user-a",
        idempotency_key="run-auto-unscaling-revision",
        request=CreateSandboxRunRequest(),
    )
    code = await repository.get_analysis_code(
        project_id="project-a", code_version_id=run.code_version_id
    )

    assert code is not None
    assert code.prompt_version == "analysis.code_revision.v1"
    assert "line_y = model.predict(X)" in code.source_code
    assert "inverse z-score unscaling" in code_ai.calls[1]["input_payload"]["recoverable_error"]


@pytest.mark.asyncio
async def test_code_generation_revises_undefined_attribute_call_before_queueing(tmp_path) -> None:
    repository, _, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    undefined_stats_alias = """
import matplotlib.pyplot as plt
from scipy import stats
from sandbox_sdk import emit_chart, emit_result, load_dataset

df = load_dataset()
statss.shapiro(df["outcome"])
figure, axis = plt.subplots()
axis.plot(df["predictor"], df["outcome"], label="Fitted trend")
emit_chart("analysis", figure)
plt.close(figure)
emit_result({"input_row_count": len(df), "analyzed_row_count": len(df)})
"""
    code_ai = FakeProjectAIClient(
        responses=[{"source_code": undefined_stats_alias}, {"source_code": VALID_CODE}]
    )
    service, _ = make_execution_service(repository, code_ai)

    run = await service.queue_run(
        project_id="project-a",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        actor_id="user-a",
        idempotency_key="run-undefined-name-revision",
        request=CreateSandboxRunRequest(),
    )
    code = await repository.get_analysis_code(
        project_id="project-a", code_version_id=run.code_version_id
    )

    assert code is not None
    assert code.revision_count == 1
    assert "undefined name 'statss'" in code_ai.calls[1]["input_payload"]["recoverable_error"]


@pytest.mark.asyncio
async def test_code_generation_revises_unsafe_statsmodels_prediction_design(tmp_path) -> None:
    repository, _, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    implicit_prediction_constant = """
import matplotlib.pyplot as plt
import pandas as pd
import statsmodels.api as sm
from sandbox_sdk import emit_chart, emit_result, load_dataset

df = load_dataset()
training_design = sm.add_constant(df[["predictor"]])
model = sm.OLS(df["outcome"], training_design).fit()
prediction_design = pd.DataFrame({"predictor": df["predictor"]})
prediction_design = sm.add_constant(prediction_design)
fitted = model.predict(prediction_design)
figure, axis = plt.subplots()
axis.plot(df["predictor"], fitted, label="Fitted trend")
emit_chart("analysis", figure)
plt.close(figure)
emit_result({"input_row_count": len(df), "analyzed_row_count": len(df)})
"""
    explicit_prediction_constant = implicit_prediction_constant.replace(
        "sm.add_constant(prediction_design)",
        "sm.add_constant(prediction_design, has_constant='add')",
    )
    code_ai = FakeProjectAIClient(
        responses=[
            {"source_code": implicit_prediction_constant},
            {"source_code": explicit_prediction_constant},
        ]
    )
    service, _ = make_execution_service(repository, code_ai)

    run = await service.queue_run(
        project_id="project-a",
        plan_id=plan.plan_id,
        plan_version=plan.version,
        actor_id="user-a",
        idempotency_key="run-prediction-design-revision",
        request=CreateSandboxRunRequest(),
    )
    code = await repository.get_analysis_code(
        project_id="project-a", code_version_id=run.code_version_id
    )

    assert code is not None
    assert code.revision_count == 1
    assert "has_constant='add'" in code.source_code
    assert "prediction design" in code_ai.calls[1]["input_payload"]["recoverable_error"]


@pytest.mark.asyncio
async def test_worker_is_idempotent_and_completes_unvalidated_run(tmp_path) -> None:
    repository, store, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    code_ai = FakeProjectAIClient(responses=[{"source_code": VALID_CODE}])
    service, signer = make_execution_service(repository, code_ai)
    first = await service.queue_run(
        project_id="project-a", plan_id=plan.plan_id, plan_version=plan.version,
        actor_id="user-a", idempotency_key="run-duplicate", request=CreateSandboxRunRequest(),
    )
    duplicate = await service.queue_run(
        project_id="project-a", plan_id=plan.plan_id, plan_version=plan.version,
        actor_id="user-a", idempotency_key="run-duplicate", request=CreateSandboxRunRequest(),
    )
    launcher = SuccessfulLauncher(write_artifact=True)
    worker = DurableExecutionWorker(
        repository=repository,
        object_store=store,
        runner=EphemeralRunner(workspace_root=tmp_path / "workspaces", launcher=launcher),
        manifest_signer=signer,
        worker_id="worker-a",
    )
    completed = await worker.process_next()

    assert duplicate.run_id == first.run_id
    assert len(repository.sandbox_runs) == 1
    assert len(code_ai.calls) == 1
    listed = await FrontendQueryService(
        repository=repository, object_store=store
    ).list_runs(
        project_id="project-a", plan_id=plan.plan_id, plan_version=plan.version
    )
    assert [item.run_id for item in listed] == [first.run_id]
    assert completed.status is SandboxRunStatus.COMPLETED_UNVALIDATED
    assert launcher.calls == 1
    artifacts = await service.list_artifacts(project_id="project-a", run_id=first.run_id)
    assert [(item.artifact_type, item.filename) for item in artifacts] == [("table", "tables/summary.csv")]
    assert await worker.process_next() is None


@pytest.mark.asyncio
async def test_cancel_and_lease_recovery(tmp_path) -> None:
    repository, store, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    code_ai = FakeProjectAIClient(responses=[{"source_code": VALID_CODE}, {"source_code": VALID_CODE}])
    service, signer = make_execution_service(repository, code_ai)
    cancelled = await service.queue_run(
        project_id="project-a", plan_id=plan.plan_id, plan_version=plan.version,
        actor_id="user-a", idempotency_key="run-cancel", request=CreateSandboxRunRequest(),
    )
    assert (await service.cancel_run(project_id="project-a", run_id=cancelled.run_id, actor_id="user-a")).status is SandboxRunStatus.CANCELLED

    recoverable = await service.queue_run(
        project_id="project-a", plan_id=plan.plan_id, plan_version=plan.version,
        actor_id="user-a", idempotency_key="run-recover", request=CreateSandboxRunRequest(),
    )
    now = datetime.now(UTC)
    first_claim = await repository.claim_sandbox_run(worker_id="crashed-worker", now=now, lease_seconds=1)
    assert first_claim.run_id == recoverable.run_id and first_claim.status is SandboxRunStatus.RUNNING
    launcher = SuccessfulLauncher()
    recovered = await DurableExecutionWorker(
        repository=repository,
        object_store=store,
        runner=EphemeralRunner(workspace_root=tmp_path / "workspaces", launcher=launcher),
        manifest_signer=signer,
        worker_id="recovery-worker",
        lease_seconds=10,
    ).process_next(now=now + timedelta(seconds=2))

    assert recovered.run_id == recoverable.run_id
    assert recovered.status is SandboxRunStatus.COMPLETED_UNVALIDATED
    assert cancelled.run_id != recovered.run_id


@pytest.mark.asyncio
async def test_code_revision_is_limited_to_one_recoverable_retry(tmp_path) -> None:
    repository, _, _, plans, plan = await approved_execution_context(tmp_path)
    await approve_plan(plans, plan)
    generation = CodeGenerationService(
        repository=repository,
        ai_client=FakeProjectAIClient(responses=[{"source_code": VALID_CODE}, {"source_code": VALID_CODE}]),
    )
    code, _ = await generation.generate(project_id="project-a", plan_id=plan.plan_id, plan_version=plan.version)
    revised = await generation.revise(
        project_id="project-a", code_version_id=code.code_version_id, recoverable_error="missing dependency"
    )

    assert revised.version == 2 and revised.revision_count == 1
    with pytest.raises(CodePolicyRejected):
        await generation.revise(
            project_id="project-a", code_version_id=revised.code_version_id, recoverable_error="still failing"
        )
