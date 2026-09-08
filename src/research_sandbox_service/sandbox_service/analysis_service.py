"""Question clarification, metadata-only plan generation, and append-only review."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol
from uuid import uuid4

from sandbox_service.domain.analysis_plans import (
    AnalysisIntent,
    AnalysisObjective,
    AnalysisPlanContent,
    AnalysisPlanDecision,
    AnalysisPlanStatus,
    AnalysisPlanVersion,
    AnalysisQuestionClarification,
    CreateAnalysisPlanRequest,
    CreateAnalysisQuestionRequest,
    ReviewAnalysisPlanRequest,
)
from sandbox_service.domain.datasets import AnalysisQuestion, AnalysisQuestionStatus, DatasetProfile, DatasetRecord
from sandbox_service.domain.errors import (
    AnalysisPlanNotFound,
    AnalysisPlanStateError,
    AnalysisQuestionIncomplete,
    DatasetNotFound,
    DatasetValidationFailed,
    ResearchContextStale,
)
from sandbox_service.domain.ports import ProjectAIClient
from sandbox_service.domain.sessions import ResearchContextSnapshot


class AnalysisRepository(Protocol):
    async def get_dataset(self, *, project_id: str, dataset_id: str, include_deleted: bool = False) -> DatasetRecord | None: ...

    async def get_dataset_profile(self, *, project_id: str, dataset_id: str, version: int) -> DatasetProfile | None: ...

    async def list_dataset_profiles(self, *, project_id: str, dataset_id: str) -> list[DatasetProfile]: ...

    async def get_context_snapshot(self, *, context_id: str) -> ResearchContextSnapshot | None: ...

    async def save_analysis_question(self, question: AnalysisQuestion) -> AnalysisQuestion: ...

    async def get_analysis_question(self, *, project_id: str, dataset_id: str, question_id: str) -> AnalysisQuestion | None: ...

    async def save_analysis_plan(self, plan: AnalysisPlanVersion) -> AnalysisPlanVersion: ...

    async def get_analysis_plan(self, *, project_id: str, plan_id: str, version: int) -> AnalysisPlanVersion | None: ...

    async def save_analysis_plan_decision(self, decision: AnalysisPlanDecision) -> AnalysisPlanDecision: ...

    async def commit_analysis_plan_review(
        self, plan: AnalysisPlanVersion, decision: AnalysisPlanDecision
    ) -> tuple[AnalysisPlanVersion, AnalysisPlanDecision]: ...

    async def get_analysis_plan_decision_by_idempotency(self, *, project_id: str, idempotency_key: str) -> AnalysisPlanDecision | None: ...


class AnalysisPlanService:
    """AI sees aggregate metadata and trusted context, never storage bytes or data rows."""

    def __init__(self, *, repository: AnalysisRepository, ai_client: ProjectAIClient) -> None:
        self._repository = repository
        self._ai_client = ai_client

    async def clarify_question(
        self,
        *,
        project_id: str,
        dataset_id: str,
        actor_id: str,
        request: CreateAnalysisQuestionRequest,
        correlation_id: str | None = None,
    ) -> AnalysisQuestion | AnalysisQuestionClarification:
        profile = await self._latest_profile(project_id=project_id, dataset_id=dataset_id)
        context = await self._load_context(project_id=project_id, context_id=request.context_snapshot_id)
        missing = self._missing_fields(request)
        self._validate_selected_columns(intent=request, profile=profile)
        if missing:
            generated = await self._ai_client.invoke_structured(
                project_id=project_id,
                operation="question_clarification",
                prompt_version="analysis.question_clarification.v1",
                input_payload={
                    "intent": request.model_dump(mode="json", exclude={"context_snapshot_id"}),
                    "missing_fields": missing,
                    "dataset_profile": self._profile_payload(profile),
                    "research_context": self._context_payload(context),
                    "output_language": request.output_language,
                },
                output_schema=AnalysisQuestionClarification,
                correlation_id=correlation_id or str(uuid4()),
            )
            content = AnalysisQuestionClarification.model_validate(generated)
            incomplete_question = await self._repository.save_analysis_question(
                self._question_from_request(
                    project_id=project_id,
                    dataset_id=dataset_id,
                    profile=profile,
                    context=context,
                    request=request,
                    status=AnalysisQuestionStatus.QUESTION_INCOMPLETE,
                )
            )
            return AnalysisQuestionClarification(
                question_id=incomplete_question.question_id,
                missing_fields=missing,
                clarification_questions=content.clarification_questions,
            )

        question = self._question_from_request(
            project_id=project_id,
            dataset_id=dataset_id,
            profile=profile,
            context=context,
            request=request,
            status=AnalysisQuestionStatus.DRAFT,
        )
        return await self._repository.save_analysis_question(question)

    async def create_plan(
        self,
        *,
        project_id: str,
        dataset_id: str,
        actor_id: str,
        request: CreateAnalysisPlanRequest,
        correlation_id: str | None = None,
    ) -> AnalysisPlanVersion:
        dataset = await self._require_dataset(project_id=project_id, dataset_id=dataset_id)
        question = await self._repository.get_analysis_question(
            project_id=project_id, dataset_id=dataset_id, question_id=request.question_id
        )
        if question is None:
            raise AnalysisQuestionIncomplete("A complete, project-scoped analysis question is required")
        if question.status is AnalysisQuestionStatus.QUESTION_INCOMPLETE:
            raise AnalysisQuestionIncomplete("Analysis question remains incomplete")
        profile_version = request.profile_version or question.profile_version
        if profile_version is None:
            raise AnalysisQuestionIncomplete("A dataset profile is required before plan generation")
        profile = await self._repository.get_dataset_profile(
            project_id=project_id, dataset_id=dataset_id, version=profile_version
        )
        if profile is None:
            raise DatasetNotFound("Dataset profile was not found in this project")
        context = await self._load_context(
            project_id=project_id, context_id=question.context_snapshot_id
        )
        if question.context_hash and (context is None or context.content_hash != question.context_hash):
            raise ResearchContextStale("Pinned research context is no longer available with the recorded hash")

        generated = await self._ai_client.invoke_structured(
            project_id=project_id,
            operation="plan_generation",
            prompt_version="analysis.plan_generation.v1",
            input_payload={
                "analysis_question": self._question_payload(question),
                "dataset_profile": self._profile_payload(profile),
                "research_context": self._context_payload(context),
                "output_language": question.output_language,
                "instruction": "Generate a draft plan only; do not infer missing columns or claim causal conclusions.",
            },
            output_schema=AnalysisPlanContent,
            correlation_id=correlation_id or str(uuid4()),
        )
        content = AnalysisPlanContent.model_validate(generated)
        canonical = {
            "dataset_id": dataset.dataset_id,
            "dataset_content_hash": dataset.content_hash,
            "profile_version": profile.version,
            "profile_hash": profile.profile_hash,
            "question_id": question.question_id,
            "question_version": question.version,
            "context_hash": context.content_hash if context else None,
            "objective": question.objective,
            "research_question": question.research_question,
            "outcome_columns": question.outcome_columns,
            "predictor_columns": question.predictor_columns,
            "group_columns": question.group_columns,
            "covariate_columns": question.covariate_columns,
            "output_language": question.output_language,
            "method": content.method,
            "method_rationale": content.method_rationale,
            "preprocessing_steps": content.preprocessing_steps,
            "assumption_checks": content.assumption_checks,
            "evaluation_metrics": content.evaluation_metrics,
            "limitations": content.limitations,
        }
        plan = AnalysisPlanVersion(
            **content.model_dump(),
            project_id=project_id,
            dataset_id=dataset_id,
            question_id=question.question_id,
            question_version=question.version,
            profile_version=profile.version,
            context_snapshot_id=context.context_id if context else None,
            context_hash=context.content_hash if context else None,
            objective=AnalysisObjective(question.objective),
            research_question=question.research_question,
            outcome_columns=question.outcome_columns,
            predictor_columns=question.predictor_columns,
            group_columns=question.group_columns,
            covariate_columns=question.covariate_columns,
            output_language=question.output_language,
            plan_hash=self._canonical_hash(canonical),
        )
        return await self._repository.save_analysis_plan(plan)

    async def get_plan(self, *, project_id: str, plan_id: str, version: int) -> AnalysisPlanVersion:
        plan = await self._repository.get_analysis_plan(
            project_id=project_id, plan_id=plan_id, version=version
        )
        if plan is None:
            raise AnalysisPlanNotFound("Analysis plan was not found in this project")
        return plan

    async def review_plan(
        self,
        *,
        project_id: str,
        plan_id: str,
        version: int,
        reviewer_id: str,
        idempotency_key: str,
        request: ReviewAnalysisPlanRequest,
    ) -> tuple[AnalysisPlanVersion, AnalysisPlanDecision]:
        existing = await self._repository.get_analysis_plan_decision_by_idempotency(
            project_id=project_id, idempotency_key=idempotency_key
        )
        if existing is not None:
            if (
                existing.plan_id != plan_id
                or existing.plan_version != version
                or existing.decision is not request.decision
            ):
                raise AnalysisPlanStateError(
                    "Idempotency-Key was already used for a different plan review request"
                )
            plan = await self.get_plan(project_id=project_id, plan_id=existing.plan_id, version=existing.plan_version)
            return plan, existing
        plan = await self.get_plan(project_id=project_id, plan_id=plan_id, version=version)
        allowed = {
            AnalysisPlanStatus.DRAFT: {AnalysisPlanStatus.IN_REVIEW},
            AnalysisPlanStatus.IN_REVIEW: {
                AnalysisPlanStatus.APPROVED,
                AnalysisPlanStatus.REJECTED,
                AnalysisPlanStatus.CHANGES_REQUESTED,
            },
        }
        if request.decision not in allowed.get(plan.status, set()):
            raise AnalysisPlanStateError(
                f"Cannot transition plan from {plan.status.value} to {request.decision.value}"
            )
        decision = AnalysisPlanDecision(
            project_id=project_id,
            plan_id=plan_id,
            plan_version=version,
            reviewer_id=reviewer_id,
            decision=request.decision,
            comment=request.comment,
            idempotency_key=idempotency_key,
        )
        updated = plan.model_copy(update={"status": request.decision})
        return await self._repository.commit_analysis_plan_review(updated, decision)

    async def _latest_profile(self, *, project_id: str, dataset_id: str) -> DatasetProfile:
        await self._require_dataset(project_id=project_id, dataset_id=dataset_id)
        profiles = await self._repository.list_dataset_profiles(project_id=project_id, dataset_id=dataset_id)
        if not profiles:
            raise DatasetNotFound("A deterministic dataset profile is required before question clarification")
        return max(profiles, key=lambda item: item.version)

    async def _require_dataset(self, *, project_id: str, dataset_id: str) -> DatasetRecord:
        dataset = await self._repository.get_dataset(project_id=project_id, dataset_id=dataset_id)
        if dataset is None:
            raise DatasetNotFound("Dataset was not found in this project")
        return dataset

    async def _load_context(
        self, *, project_id: str, context_id: str | None
    ) -> ResearchContextSnapshot | None:
        if context_id is None:
            return None
        snapshot = await self._repository.get_context_snapshot(context_id=context_id)
        if snapshot is None or snapshot.project_id != project_id:
            raise ResearchContextStale("Research context is unavailable for this project")
        # The frozen Pydantic contract plus this server-side lookup prevents client-supplied context mutation.
        if not snapshot.content_hash:
            raise ResearchContextStale("Research context does not have an immutable content hash")
        return snapshot

    @staticmethod
    def _missing_fields(intent: AnalysisIntent) -> list[str]:
        required: list[str] = []
        if intent.objective is AnalysisObjective.COMPARE:
            required = ["outcome_columns", "group_columns"]
        elif intent.objective in {AnalysisObjective.ASSOCIATE, AnalysisObjective.PREDICT}:
            required = ["outcome_columns", "predictor_columns"]
        return [field for field in required if not getattr(intent, field)]

    @staticmethod
    def _question_from_request(
        *,
        project_id: str,
        dataset_id: str,
        profile: DatasetProfile,
        context: ResearchContextSnapshot | None,
        request: CreateAnalysisQuestionRequest,
        status: AnalysisQuestionStatus,
    ) -> AnalysisQuestion:
        return AnalysisQuestion(
            project_id=project_id,
            dataset_id=dataset_id,
            profile_version=profile.version,
            context_snapshot_id=context.context_id if context else None,
            context_hash=context.content_hash if context else None,
            objective=request.objective.value,
            research_question=request.research_question,
            outcome_columns=request.outcome_columns,
            predictor_columns=request.predictor_columns,
            group_columns=request.group_columns,
            covariate_columns=request.covariate_columns,
            study_design=request.study_design,
            repeated_measures=request.repeated_measures,
            hypothesis=request.hypothesis,
            preferred_metrics=request.preferred_metrics,
            output_language=request.output_language,
            status=status,
        )

    @staticmethod
    def _validate_selected_columns(*, intent: AnalysisIntent, profile: DatasetProfile) -> None:
        known = {column.name for column in profile.columns}
        selected = set(
            intent.outcome_columns
            + intent.predictor_columns
            + intent.group_columns
            + intent.covariate_columns
        )
        unknown = sorted(selected - known)
        if unknown:
            raise DatasetValidationFailed("Analysis intent references columns absent from the dataset profile", details={"columns": unknown})

    @staticmethod
    def _profile_payload(profile: DatasetProfile) -> dict[str, Any]:
        return profile.model_dump(mode="json")

    @staticmethod
    def _question_payload(question: AnalysisQuestion) -> dict[str, Any]:
        return {
            "question_id": question.question_id,
            "version": question.version,
            "objective": question.objective,
            "research_question": question.research_question,
            "outcome_columns": question.outcome_columns,
            "predictor_columns": question.predictor_columns,
            "group_columns": question.group_columns,
            "covariate_columns": question.covariate_columns,
            "study_design": question.study_design,
            "repeated_measures": question.repeated_measures,
            "hypothesis": question.hypothesis,
            "preferred_metrics": question.preferred_metrics,
            "output_language": question.output_language,
        }

    @staticmethod
    def _context_payload(context: ResearchContextSnapshot | None) -> dict[str, Any] | None:
        if context is None:
            return None
        return {
            "context_id": context.context_id,
            "content_hash": context.content_hash,
            "source_status": context.source_status,
            "evidence_refs": context.evidence_refs,
            "limitations": context.limitations,
            "method_suggestions": context.method_suggestions,
            "dataset_requirements": context.dataset_requirements,
            "evaluation_metric_suggestions": context.evaluation_metric_suggestions,
        }

    @staticmethod
    def _canonical_hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
