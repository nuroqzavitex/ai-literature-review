import json

import pytest

from sandbox_service.analysis_service import AnalysisPlanService
from sandbox_service.dataset_service import DatasetService
from sandbox_service.domain.analysis_plans import (
    AnalysisPlanStatus,
    CreateAnalysisPlanRequest,
    CreateAnalysisQuestionRequest,
    ReviewAnalysisPlanRequest,
)
from sandbox_service.domain.datasets import AnalysisQuestionStatus, DatasetClassification
from sandbox_service.domain.sessions import ResearchContextSnapshot, SandboxEntrypoint
from sandbox_service.repositories.memory import InMemorySandboxSessionRepository
from sandbox_service.storage import LocalObjectStore
from tests.fakes import FakeProjectAIClient


async def create_profiled_dataset(tmp_path, repository: InMemorySandboxSessionRepository):
    datasets = DatasetService(
        repository=repository,
        object_store=LocalObjectStore(tmp_path / "objects"),
    )
    uploaded = await datasets.upload(
        project_id="project-a",
        actor_id="user-a",
        filename="measurements.csv",
        declared_media_type="text/csv",
        classification=DatasetClassification.NON_SENSITIVE,
        data=b"outcome,predictor,group\n1,10,A\n2,20,B\n",
    )
    await datasets.profile(project_id="project-a", dataset_id=uploaded.dataset_id)
    return uploaded


@pytest.mark.asyncio
async def test_generates_plan_from_profile_and_pinned_context_without_raw_rows(tmp_path) -> None:
    repository = InMemorySandboxSessionRepository()
    uploaded = await create_profiled_dataset(tmp_path, repository)
    context = ResearchContextSnapshot(
        project_id="project-a",
        source_type=SandboxEntrypoint.GRAPHRAG_ANSWER,
        source_status="reviewed",
        content_hash="sha256:pinned-context",
        evidence_refs=[{"ref": "evidence-1"}],
        method_suggestions=["linear regression"],
    )
    await repository.save_context_snapshot(context)
    ai = FakeProjectAIClient(
        responses=[
            {
                "method": "Linear regression",
                "method_rationale": "The declared outcome and predictor are numeric.",
                "preprocessing_steps": ["check missingness"],
                "assumption_checks": ["check residuals"],
                "evaluation_metrics": ["R-squared"],
                "limitations": ["Association does not establish causation"],
            }
        ]
    )
    service = AnalysisPlanService(repository=repository, ai_client=ai)
    question = await service.clarify_question(
        project_id="project-a",
        dataset_id=uploaded.dataset_id,
        actor_id="user-a",
        request=CreateAnalysisQuestionRequest(
            objective="associate",
            research_question="Is predictor associated with outcome?",
            outcome_columns=["outcome"],
            predictor_columns=["predictor"],
            context_snapshot_id=context.context_id,
            preferred_metrics=["R-squared"],
            output_language="vi",
        ),
    )
    assert question.status is AnalysisQuestionStatus.DRAFT

    plan = await service.create_plan(
        project_id="project-a",
        dataset_id=uploaded.dataset_id,
        actor_id="user-a",
        request=CreateAnalysisPlanRequest(question_id=question.question_id),
    )

    payload = ai.calls[0]["input_payload"]
    encoded_prompt = json.dumps(payload, sort_keys=True)
    assert plan.status is AnalysisPlanStatus.DRAFT
    assert plan.context_hash == context.content_hash
    assert plan.profile_version == 1
    assert plan.plan_hash
    assert plan.output_language == "vi"
    assert ai.calls[0]["prompt_version"] == "analysis.plan_generation.v1"
    assert "outcome,predictor,group" not in encoded_prompt
    assert "1,10,A" not in encoded_prompt
    assert "dataset_profile" in payload and "research_context" in payload
    assert payload["output_language"] == "vi"


@pytest.mark.asyncio
async def test_missing_information_persists_question_incomplete_and_does_not_guess(tmp_path) -> None:
    repository = InMemorySandboxSessionRepository()
    uploaded = await create_profiled_dataset(tmp_path, repository)
    ai = FakeProjectAIClient(
        responses=[
            {
                "missing_fields": ["outcome_columns", "group_columns"],
                "clarification_questions": [
                    "Which column is the outcome?",
                    "Which column identifies the comparison groups?",
                ],
            }
        ]
    )
    service = AnalysisPlanService(repository=repository, ai_client=ai)

    clarification = await service.clarify_question(
        project_id="project-a",
        dataset_id=uploaded.dataset_id,
        actor_id="user-a",
        request=CreateAnalysisQuestionRequest(
            objective="compare",
            research_question="Do groups differ?",
        ),
    )

    assert clarification.status == "question_incomplete"
    assert clarification.missing_fields == ["outcome_columns", "group_columns"]
    stored = await repository.get_analysis_question(
        project_id="project-a", dataset_id=uploaded.dataset_id, question_id=clarification.question_id
    )
    assert stored is not None and stored.status is AnalysisQuestionStatus.QUESTION_INCOMPLETE
    assert ai.calls[0]["prompt_version"] == "analysis.question_clarification.v1"


@pytest.mark.asyncio
async def test_plan_review_is_append_only_idempotent_and_updates_only_status(tmp_path) -> None:
    repository = InMemorySandboxSessionRepository()
    uploaded = await create_profiled_dataset(tmp_path, repository)
    ai = FakeProjectAIClient(
        responses=[
            {
                "method": "Descriptive summary",
                "method_rationale": "The user requested description.",
                "preprocessing_steps": [],
                "assumption_checks": [],
                "evaluation_metrics": ["mean"],
                "limitations": [],
            }
        ]
    )
    service = AnalysisPlanService(repository=repository, ai_client=ai)
    question = await service.clarify_question(
        project_id="project-a",
        dataset_id=uploaded.dataset_id,
        actor_id="user-a",
        request=CreateAnalysisQuestionRequest(
            objective="describe",
            research_question="Describe the outcome column.",
            outcome_columns=["outcome"],
        ),
    )
    plan = await service.create_plan(
        project_id="project-a",
        dataset_id=uploaded.dataset_id,
        actor_id="user-a",
        request=CreateAnalysisPlanRequest(question_id=question.question_id),
    )

    in_review, start_decision = await service.review_plan(
        project_id="project-a",
        plan_id=plan.plan_id,
        version=plan.version,
        reviewer_id="reviewer-a",
        idempotency_key="review-start-1",
        request=ReviewAnalysisPlanRequest(decision="in_review"),
    )
    approved, approval_decision = await service.review_plan(
        project_id="project-a",
        plan_id=plan.plan_id,
        version=plan.version,
        reviewer_id="reviewer-a",
        idempotency_key="review-approve-1",
        request=ReviewAnalysisPlanRequest(decision="approved", comment="Looks sound"),
    )
    repeated, repeated_decision = await service.review_plan(
        project_id="project-a",
        plan_id=plan.plan_id,
        version=plan.version,
        reviewer_id="reviewer-a",
        idempotency_key="review-approve-1",
        request=ReviewAnalysisPlanRequest(decision="approved", comment="ignored"),
    )

    assert in_review.status is AnalysisPlanStatus.IN_REVIEW
    assert approved.status is AnalysisPlanStatus.APPROVED
    assert repeated == approved
    assert repeated_decision == approval_decision
    assert len(repository.analysis_plan_decisions) == 2
    assert [item.decision for item in repository.analysis_plan_decisions] == [
        AnalysisPlanStatus.IN_REVIEW,
        AnalysisPlanStatus.APPROVED,
    ]
    assert start_decision.plan_id == approval_decision.plan_id == plan.plan_id
    assert approved.plan_hash == plan.plan_hash
    assert approved.method == plan.method
