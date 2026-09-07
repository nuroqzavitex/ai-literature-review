"""Product-level E2E journeys using only fake external adapters and isolated runner harnesses."""

from copy import deepcopy
import json

import pytest

from sandbox_service.adoption import AdoptionProposalService
from sandbox_service.analysis_service import AnalysisPlanService
from sandbox_service.code_generation_service import CodeGenerationService
from sandbox_service.dataset_service import DatasetService
from sandbox_service.domain.adoption import (
    AdoptionProposalStatus,
    AdoptionSourceType,
    CreateAdoptionProposalRequest,
    ReviewAdoptionProposalRequest,
)
from sandbox_service.domain.analysis_plans import (
    CreateAnalysisPlanRequest,
    CreateAnalysisQuestionRequest,
    ReviewAnalysisPlanRequest,
)
from sandbox_service.domain.datasets import DatasetClassification
from sandbox_service.domain.execution import CreateSandboxRunRequest, SandboxRunStatus
from sandbox_service.domain.graph_overlays import (
    CreateGraphOverlayOperationRequest,
    CreateGraphOverlayRequest,
)
from sandbox_service.domain.hypotheses import DraftStatus, GenerateHypothesisRequest, ReviewHypothesisDraftRequest
from sandbox_service.domain.results import ReviewAnalysisResultRequest
from sandbox_service.domain.sessions import CreateSandboxSessionRequest
from sandbox_service.execution.manifest import ManifestSigner
from sandbox_service.execution.runner import EphemeralRunner, ExecutionResult
from sandbox_service.execution_service import ExecutionService
from sandbox_service.graph_overlay import GraphOverlaySandboxService
from sandbox_service.hypothesis_graph import HypothesisSandboxGraph
from sandbox_service.integration.auth import ContextSnapshotSigner
from sandbox_service.integration.context_mapping import ResearchContextMapper
from sandbox_service.repositories.memory import InMemorySandboxSessionRepository
from sandbox_service.result_service import ResultReviewService
from sandbox_service.session_service import SandboxSessionService
from sandbox_service.storage import LocalObjectStore
from sandbox_service.worker import DurableExecutionWorker
from tests.fakes import FakeGraphSnapshotReader, FakeProjectAIClient, FakeResearchContextProvider


PROJECT = "project-e2e"
ACTOR = "researcher-e2e"
RAW_CSV = b"outcome,predictor\n1,2\n2,3\n"
VALID_CODE = """
import matplotlib.pyplot as plt
from sandbox_sdk import emit_chart, emit_result, load_dataset

df = load_dataset()
figure, axis = plt.subplots()
axis.plot([0], [0])
emit_chart("analysis", figure)
plt.close(figure)
emit_result({"schema_version": "analysis_result.v1", "artifact_refs": ["charts/analysis.png"]})
"""


def context_mapper() -> ResearchContextMapper:
    return ResearchContextMapper(
        snapshot_signer=ContextSnapshotSigner(signing_key=b"e2e-context-signing-key-that-is-at-least-32-bytes")
    )


@pytest.mark.asyncio
async def test_e2e_hypothesis_from_graphrag_context_to_reviewer_approval() -> None:
    repository = InMemorySandboxSessionRepository()
    mapper = context_mapper()
    snapshot = mapper.graphrag_answer(
        project_id=PROJECT,
        answer_id="answer-e2e-1",
        graph_version_id="graph-v1",
        evidence_refs=[{"evidence_id": "evidence-1", "version": "1"}],
        research_question="Is intervention associated with improved outcome?",
        limitations=["Evidence is scoped to the pinned answer."],
    )
    session = await SandboxSessionService(
        repository=repository,
        context_provider=FakeResearchContextProvider({(PROJECT, "answer-e2e-1"): snapshot}),
    ).create_session(
        project_id=PROJECT,
        actor_id=ACTOR,
        request=CreateSandboxSessionRequest(
            mode="hypothesis", entrypoint="graphrag_answer", source_resource_id="answer-e2e-1",
            title="Open GraphRAG answer in Sandbox",
        ),
    )
    ai = FakeProjectAIClient(responses=[
        {
            "statement": "The intervention is associated with improved outcome.",
            "rationale": "The pinned evidence supports a falsifiable association.",
            "supporting_evidence_refs": ["evidence-1"], "counterevidence_refs": [],
            "assumptions": ["Outcome is measured consistently"],
            "falsification_criteria": ["No association in a registered comparison"],
            "required_data": ["Non-sensitive outcome measurements"],
            "limitations": ["Not a causal conclusion"],
        },
        {
            "objective": "Compare the outcome by intervention exposure.",
            "independent_variables": ["intervention"], "dependent_variables": ["outcome"],
            "controls": ["baseline outcome"], "data_requirements": ["future cohort"],
            "method_candidates": ["controlled comparison"], "evaluation_metrics": ["effect size"],
            "assumption_checks": ["group comparability"], "stopping_criteria": ["pre-registered sample size"],
            "risks": ["confounding"],
        },
    ])
    graph = HypothesisSandboxGraph(repository=repository, ai_client=ai)

    hypothesis = await graph.generate_hypothesis(project_id=PROJECT, session_id=session.session_id, actor_id=ACTOR)
    experiment = await graph.generate_experiment(
        project_id=PROJECT, session_id=session.session_id, hypothesis_id=hypothesis.hypothesis_id, actor_id=ACTOR
    )
    reviewed = await graph.review_hypothesis(
        project_id=PROJECT, session_id=session.session_id, hypothesis_id=hypothesis.hypothesis_id,
        reviewer_id="reviewer-e2e", request=ReviewHypothesisDraftRequest(decision="reviewed"),
    )

    assert session.context_hash == snapshot.content_hash
    assert reviewed.status is DraftStatus.REVIEWED
    assert experiment.hypothesis_id == hypothesis.hypothesis_id
    assert [call["operation"] for call in ai.calls] == ["hypothesis_generation", "experiment_design"]


@pytest.mark.asyncio
async def test_e2e_candidate_overlay_is_hypothetical_and_adoption_remains_a_proposal() -> None:
    repository = InMemorySandboxSessionRepository()
    mapper = context_mapper()
    snapshot = mapper.discovery_candidate(
        project_id=PROJECT, candidate_id="candidate-e2e-1", discovery_run_id="discovery-v1",
        graph_version_id="graph-v1", evidence_refs=[{"evidence_id": "candidate-evidence"}],
        limitations=["Candidate remains hypothetical."],
    )
    session = await SandboxSessionService(
        repository=repository,
        context_provider=FakeResearchContextProvider({(PROJECT, "candidate-e2e-1"): snapshot}),
    ).create_session(
        project_id=PROJECT, actor_id=ACTOR,
        request=CreateSandboxSessionRequest(
            mode="graph_overlay", entrypoint="validated_candidate", source_resource_id="candidate-e2e-1",
            title="Test this candidate",
        ),
    )
    base = {"nodes": [{"id": "A"}, {"id": "B"}, {"id": "C"}], "edges": [{"source": "A", "target": "B", "type": "supports"}]}
    original = deepcopy(base)
    overlays = GraphOverlaySandboxService(
        repository=repository, graph_reader=FakeGraphSnapshotReader({(PROJECT, "graph-v1"): base})
    )
    overlay = await overlays.create_overlay(
        project_id=PROJECT, session_id=session.session_id, actor_id=ACTOR,
        request=CreateGraphOverlayRequest(base_graph_version_id="graph-v1"),
    )
    added = await overlays.add_operation(
        project_id=PROJECT, session_id=session.session_id, overlay_id=overlay.overlay_id,
        request=CreateGraphOverlayOperationRequest(
            operation="add_edge", entity_or_edge_type="supports", source_ref="B", target_ref="C",
            rationale="Hypothetical candidate relation", evidence_refs=["candidate-evidence"],
        ),
    )
    removed = await overlays.add_operation(
        project_id=PROJECT, session_id=session.session_id, overlay_id=overlay.overlay_id,
        request=CreateGraphOverlayOperationRequest(
            operation="remove_edge", entity_or_edge_type="supports", source_ref="A", target_ref="B",
            rationale="Counterfactual removal", evidence_refs=["candidate-evidence"],
        ),
    )
    assessment = await overlays.assess(project_id=PROJECT, session_id=session.session_id, overlay_id=overlay.overlay_id, actor_id=ACTOR)
    adoption = AdoptionProposalService(repository=repository)
    proposal = await adoption.create(
        project_id=PROJECT, session_id=session.session_id, actor_id=ACTOR,
        request=CreateAdoptionProposalRequest(
            source_type=AdoptionSourceType.OVERLAY_ASSESSMENT, source_id=assessment.assessment_id,
            rationale="Request core review as a draft only.",
        ),
    )
    await adoption.review(
        project_id=PROJECT, proposal_id=proposal.proposal_id, reviewer_id="reviewer-e2e",
        request=ReviewAdoptionProposalRequest(decision=AdoptionProposalStatus.IN_REVIEW),
    )
    approved = await adoption.review(
        project_id=PROJECT, proposal_id=proposal.proposal_id, reviewer_id="reviewer-e2e",
        request=ReviewAdoptionProposalRequest(decision=AdoptionProposalStatus.APPROVED, reason="Hand off draft"),
    )

    assert added.hypothetical is True and removed.hypothetical is True
    assert assessment.status.value == "assessed"
    assert approved.status is AdoptionProposalStatus.APPROVED
    assert base == original  # no graph write path exists


class ResultWritingLauncher:
    def __init__(self) -> None:
        self.calls = 0
        self.workspace = None
        self.code_path = None

    async def run(self, **kwargs) -> ExecutionResult:
        self.calls += 1
        self.workspace = kwargs["workspace"]
        self.code_path = kwargs["code_path"]
        payload = {
            "schema_version": "analysis_result.v1", "objective": "associate", "method": "Linear regression",
            "input_row_count": 2, "analyzed_row_count": 2, "preprocessing_applied": [],
            "assumption_checks": [{"name": "residual diagnostics", "passed": True}],
            "metrics": [{"name": "R-squared", "value": 0.8}], "statistical_results": [],
            "warnings": [], "limitations": ["Association only"], "artifact_refs": ["analysis_result.json"],
            "narrative": ["The observed relationship should be interpreted cautiously."],
        }
        (kwargs["output_dir"] / "analysis_result.json").write_text(json.dumps(payload), encoding="utf-8")
        return ExecutionResult(exit_code=0)


@pytest.mark.asyncio
async def test_e2e_data_analysis_from_upload_to_validated_reviewed_reproducible_result(tmp_path) -> None:
    repository = InMemorySandboxSessionRepository()
    store = LocalObjectStore(tmp_path / "objects")
    session = await SandboxSessionService(repository=repository).create_session(
        project_id=PROJECT, actor_id=ACTOR,
        request=CreateSandboxSessionRequest(mode="data_analysis", entrypoint="manual", title="Analyze uploaded fixture"),
    )
    datasets = DatasetService(repository=repository, object_store=store)
    uploaded = await datasets.upload(
        project_id=PROJECT, actor_id=ACTOR, filename="analysis.csv", declared_media_type="text/csv",
        classification=DatasetClassification.NON_SENSITIVE, data=RAW_CSV,
    )
    profile = await datasets.profile(project_id=PROJECT, dataset_id=uploaded.dataset_id)
    plan_ai = FakeProjectAIClient(responses=[{
        "method": "Linear regression", "method_rationale": "Numeric outcome and predictor.",
        "preprocessing_steps": [], "assumption_checks": ["residual diagnostics"],
        "evaluation_metrics": ["R-squared"], "limitations": ["Association only"],
    }])
    plans = AnalysisPlanService(repository=repository, ai_client=plan_ai)
    question = await plans.clarify_question(
        project_id=PROJECT, dataset_id=uploaded.dataset_id, actor_id=ACTOR,
        request=CreateAnalysisQuestionRequest(
            objective="associate", research_question="Is predictor associated with outcome?",
            outcome_columns=["outcome"], predictor_columns=["predictor"],
        ),
    )
    plan = await plans.create_plan(
        project_id=PROJECT, dataset_id=uploaded.dataset_id, actor_id=ACTOR,
        request=CreateAnalysisPlanRequest(question_id=question.question_id),
    )
    await plans.review_plan(
        project_id=PROJECT, plan_id=plan.plan_id, version=plan.version, reviewer_id="reviewer-e2e",
        idempotency_key="plan-in-review", request=ReviewAnalysisPlanRequest(decision="in_review"),
    )
    approved_plan, _ = await plans.review_plan(
        project_id=PROJECT, plan_id=plan.plan_id, version=plan.version, reviewer_id="reviewer-e2e",
        idempotency_key="plan-approved", request=ReviewAnalysisPlanRequest(decision="approved"),
    )
    code_ai = FakeProjectAIClient(responses=[{"source_code": VALID_CODE}])
    signer = ManifestSigner(signing_key=b"e2e-manifest-signing-key-that-is-at-least-32-bytes")
    execution = ExecutionService(
        repository=repository, code_generation=CodeGenerationService(repository=repository, ai_client=code_ai),
        manifest_signer=signer, image_digest="sandbox-runtime@sha256:" + "3" * 64,
        package_manifest_hash="4" * 64,
    )
    run = await execution.queue_run(
        project_id=PROJECT, plan_id=approved_plan.plan_id, plan_version=approved_plan.version,
        actor_id=ACTOR, idempotency_key="execute-once", request=CreateSandboxRunRequest(random_seed=11),
    )
    interpretation_ai = FakeProjectAIClient(responses=[{
        "narrative": ["The reported fit is supported by the validated result."],
        "numeric_claims": [{"statement": "The R-squared was 0.8.", "value": 0.8, "locator": "/metrics/0/value"}],
        "limitations": ["Association only"],
    }])
    result_service = ResultReviewService(repository=repository, object_store=store, ai_client=interpretation_ai)
    launcher = ResultWritingLauncher()
    worker = DurableExecutionWorker(
        repository=repository, object_store=store,
        runner=EphemeralRunner(workspace_root=tmp_path / "workspaces", launcher=launcher),
        manifest_signer=signer, worker_id="e2e-worker",
    )
    completed = await worker.process_next()
    validation = await result_service.validate_run(project_id=PROJECT, run_id=run.run_id)
    interpretation, citations = await result_service.interpret_validated(project_id=PROJECT, run_id=run.run_id)
    assert (await execution.get_run(project_id=PROJECT, run_id=run.run_id)).status is SandboxRunStatus.RESULT_REVIEW_WAITING
    reviewed_run, _ = await result_service.review_result(
        project_id=PROJECT, run_id=run.run_id, reviewer_id="reviewer-e2e", idempotency_key="result-approved",
        request=ReviewAnalysisResultRequest(decision="approved"),
    )
    bundle = await result_service.get_bundle(project_id=PROJECT, run_id=run.run_id)

    prompt_text = "\n".join(str(call["input_payload"]) for client in (plan_ai, code_ai, interpretation_ai) for call in client.calls)
    assert session.mode.value == "data_analysis" and profile.row_count == 2
    assert completed.status is SandboxRunStatus.COMPLETED_UNVALIDATED
    assert validation.status.value == "validated"
    assert (
        launcher.calls == 1
        and launcher.code_path.parent.name == "code"
        and launcher.code_path.parent.parent == launcher.workspace
        and not launcher.workspace.exists()
    )
    assert RAW_CSV.decode() not in prompt_text
    assert RAW_CSV.decode() not in repr(repository.__dict__)  # metadata/audit state never stores raw rows
    assert len(interpretation.numeric_claims) == len(citations) == 1
    assert reviewed_run.status is SandboxRunStatus.APPROVED
    assert bundle.result_hash and bundle.dataset_hash == uploaded.content_hash
