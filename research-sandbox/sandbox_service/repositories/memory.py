"""Small in-memory repository for standalone S0 development and unit tests."""

from datetime import timedelta

from sandbox_service.domain.adoption import AdoptionDecision, AdoptionProposal
from sandbox_service.domain.analysis_plans import AnalysisPlanDecision, AnalysisPlanVersion
from sandbox_service.domain.datasets import AnalysisQuestion, DatasetProfile, DatasetRecord
from sandbox_service.domain.execution import (
    AnalysisArtifact,
    AnalysisCodeVersion,
    SandboxRun,
    SandboxRunStatus,
    SandboxRunStatusHistory,
)
from sandbox_service.domain.graph_overlays import (
    GraphOverlay,
    GraphOverlayOperation,
    OverlayAssessment,
)
from sandbox_service.domain.hypotheses import ExperimentDraft, HypothesisDraft
from sandbox_service.domain.results import (
    AnalysisCitation,
    AnalysisReproducibilityBundle,
    AnalysisResultInterpretationRecord,
    AnalysisResultReview,
    AnalysisResultValidation,
)
from sandbox_service.domain.sessions import (
    ResearchContextSnapshot,
    SandboxSessionResponse,
    SandboxSessionStatusHistory,
)


class InMemorySandboxSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, SandboxSessionResponse] = {}
        self.context_snapshots: dict[str, ResearchContextSnapshot] = {}
        self.status_history: list[dict[str, str | None]] = []
        self.session_status_history: list[SandboxSessionStatusHistory] = []
        self.hypotheses: dict[str, HypothesisDraft] = {}
        self.experiments: dict[str, ExperimentDraft] = {}
        self.overlays: dict[str, GraphOverlay] = {}
        self.overlay_operations: dict[str, list[GraphOverlayOperation]] = {}
        self.overlay_assessments: dict[str, OverlayAssessment] = {}
        self.adoption_proposals: dict[str, AdoptionProposal] = {}
        self.adoption_decisions: list[AdoptionDecision] = []
        self.datasets: dict[str, DatasetRecord] = {}
        self.dataset_profiles: dict[str, list[DatasetProfile]] = {}
        self.analysis_questions: dict[str, AnalysisQuestion] = {}
        self.analysis_plans: dict[tuple[str, int], AnalysisPlanVersion] = {}
        self.analysis_plan_decisions: list[AnalysisPlanDecision] = []
        self.analysis_plan_decisions_by_idempotency: dict[tuple[str, str], AnalysisPlanDecision] = {}
        self.analysis_code_versions: dict[str, AnalysisCodeVersion] = {}
        self.sandbox_runs: dict[str, SandboxRun] = {}
        self.sandbox_runs_by_idempotency: dict[tuple[str, str], SandboxRun] = {}
        self.sandbox_run_status_history: list[SandboxRunStatusHistory] = []
        self.analysis_artifacts: dict[str, list[AnalysisArtifact]] = {}
        self.consumed_manifest_nonces: dict[str, str] = {}
        self.result_validations: dict[str, AnalysisResultValidation] = {}
        self.result_interpretations: dict[str, AnalysisResultInterpretationRecord] = {}
        self.analysis_citations: dict[str, list[AnalysisCitation]] = {}
        self.analysis_result_reviews: list[AnalysisResultReview] = []
        self.analysis_result_reviews_by_idempotency: dict[tuple[str, str], AnalysisResultReview] = {}
        self.reproducibility_bundles: dict[str, AnalysisReproducibilityBundle] = {}

    async def save_context_snapshot(self, snapshot: ResearchContextSnapshot) -> None:
        self.context_snapshots[snapshot.context_id] = snapshot

    async def create_session(self, session: SandboxSessionResponse) -> SandboxSessionResponse:
        self.sessions[session.session_id] = session
        history = SandboxSessionStatusHistory(
            session_id=session.session_id,
            project_id=session.project_id,
            to_status=session.status,
            changed_by=session.creator_id,
            reason="session_created",
            created_at=session.created_at,
        )
        self.session_status_history.append(history)
        self.status_history.append(
            {
                "session_id": session.session_id,
                "project_id": session.project_id,
                "from_status": None,
                "to_status": session.status.value,
            }
        )
        return session

    async def update_session_status(
        self,
        session: SandboxSessionResponse,
        *,
        changed_by: str,
        reason: str | None = None,
    ) -> SandboxSessionResponse:
        previous = self.sessions.get(session.session_id)
        if previous is None or previous.project_id != session.project_id:
            raise KeyError(session.session_id)
        self.sessions[session.session_id] = session
        if previous.status is not session.status:
            history = SandboxSessionStatusHistory(
                session_id=session.session_id,
                project_id=session.project_id,
                from_status=previous.status,
                to_status=session.status,
                changed_by=changed_by,
                reason=reason,
                created_at=session.updated_at,
            )
            self.session_status_history.append(history)
            self.status_history.append(
                {
                    "session_id": session.session_id,
                    "project_id": session.project_id,
                    "from_status": previous.status.value,
                    "to_status": session.status.value,
                }
            )
        return session

    async def list_session_status_history(
        self, *, project_id: str, session_id: str
    ) -> list[SandboxSessionStatusHistory]:
        session = await self.get_session(project_id=project_id, session_id=session_id)
        if session is None:
            return []
        return [
            item
            for item in self.session_status_history
            if item.project_id == project_id and item.session_id == session_id
        ]

    async def get_session(
        self, *, project_id: str, session_id: str
    ) -> SandboxSessionResponse | None:
        session = self.sessions.get(session_id)
        if session is None or session.project_id != project_id:
            return None
        return session

    async def list_sessions(self, *, project_id: str) -> list[SandboxSessionResponse]:
        return sorted(
            (item for item in self.sessions.values() if item.project_id == project_id),
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def get_context_snapshot(self, *, context_id: str) -> ResearchContextSnapshot | None:
        return self.context_snapshots.get(context_id)

    async def save_hypothesis(self, draft: HypothesisDraft) -> HypothesisDraft:
        self.hypotheses[draft.hypothesis_id] = draft
        return draft

    async def get_hypothesis(
        self, *, project_id: str, session_id: str, hypothesis_id: str
    ) -> HypothesisDraft | None:
        draft = self.hypotheses.get(hypothesis_id)
        if draft is None or draft.session_id != session_id:
            return None
        session = await self.get_session(project_id=project_id, session_id=session_id)
        return draft if session else None

    async def list_hypotheses(
        self, *, project_id: str, session_id: str
    ) -> list[HypothesisDraft]:
        if await self.get_session(project_id=project_id, session_id=session_id) is None:
            return []
        return [draft for draft in self.hypotheses.values() if draft.session_id == session_id]

    async def save_experiment(self, draft: ExperimentDraft) -> ExperimentDraft:
        self.experiments[draft.experiment_id] = draft
        return draft

    async def get_experiment(
        self, *, project_id: str, session_id: str, experiment_id: str
    ) -> ExperimentDraft | None:
        draft = self.experiments.get(experiment_id)
        if draft is None or draft.session_id != session_id:
            return None
        session = await self.get_session(project_id=project_id, session_id=session_id)
        return draft if session else None

    async def list_experiments(
        self, *, project_id: str, session_id: str
    ) -> list[ExperimentDraft]:
        if await self.get_session(project_id=project_id, session_id=session_id) is None:
            return []
        return [draft for draft in self.experiments.values() if draft.session_id == session_id]

    async def save_overlay(self, overlay: GraphOverlay) -> GraphOverlay:
        self.overlays[overlay.overlay_id] = overlay
        self.overlay_operations.setdefault(overlay.overlay_id, [])
        return overlay

    async def get_overlay(
        self, *, project_id: str, session_id: str, overlay_id: str
    ) -> GraphOverlay | None:
        overlay = self.overlays.get(overlay_id)
        if overlay is None or overlay.session_id != session_id or overlay.project_id != project_id:
            return None
        return overlay

    async def list_overlays(self, *, project_id: str, session_id: str) -> list[GraphOverlay]:
        if await self.get_session(project_id=project_id, session_id=session_id) is None:
            return []
        return sorted(
            (
                overlay
                for overlay in self.overlays.values()
                if overlay.project_id == project_id and overlay.session_id == session_id
            ),
            key=lambda overlay: overlay.updated_at,
            reverse=True,
        )

    async def save_overlay_operation(self, operation: GraphOverlayOperation) -> GraphOverlayOperation:
        self.overlay_operations.setdefault(operation.overlay_id, []).append(operation)
        return operation

    async def list_overlay_operations(self, *, overlay_id: str) -> list[GraphOverlayOperation]:
        return list(self.overlay_operations.get(overlay_id, []))

    async def save_assessment(self, assessment: OverlayAssessment) -> OverlayAssessment:
        self.overlay_assessments[assessment.overlay_id] = assessment
        return assessment

    async def get_assessment(self, *, overlay_id: str) -> OverlayAssessment | None:
        return self.overlay_assessments.get(overlay_id)

    async def get_assessment_by_id(self, *, assessment_id: str) -> OverlayAssessment | None:
        return next(
            (
                assessment
                for assessment in self.overlay_assessments.values()
                if assessment.assessment_id == assessment_id
            ),
            None,
        )

    async def save_adoption_proposal(self, proposal: AdoptionProposal) -> AdoptionProposal:
        self.adoption_proposals[proposal.proposal_id] = proposal
        return proposal

    async def get_adoption_proposal(
        self, *, project_id: str, session_id: str, proposal_id: str
    ) -> AdoptionProposal | None:
        proposal = self.adoption_proposals.get(proposal_id)
        if proposal is None or proposal.project_id != project_id or proposal.session_id != session_id:
            return None
        return proposal

    async def find_adoption_proposal(
        self, *, project_id: str, proposal_id: str
    ) -> AdoptionProposal | None:
        proposal = self.adoption_proposals.get(proposal_id)
        if proposal is None or proposal.project_id != project_id:
            return None
        return proposal

    async def list_adoption_proposals(
        self, *, project_id: str, session_id: str
    ) -> list[AdoptionProposal]:
        return [
            proposal
            for proposal in self.adoption_proposals.values()
            if proposal.project_id == project_id and proposal.session_id == session_id
        ]

    async def save_adoption_decision(self, decision: AdoptionDecision) -> AdoptionDecision:
        self.adoption_decisions.append(decision)
        return decision

    async def save_dataset(self, dataset: DatasetRecord) -> DatasetRecord:
        self.datasets[dataset.dataset_id] = dataset
        return dataset

    async def get_dataset(
        self, *, project_id: str, dataset_id: str, include_deleted: bool = False
    ) -> DatasetRecord | None:
        dataset = self.datasets.get(dataset_id)
        if dataset is None or dataset.project_id != project_id:
            return None
        if not include_deleted and dataset.deleted_at is not None:
            return None
        return dataset

    async def list_datasets(self, *, project_id: str) -> list[DatasetRecord]:
        return sorted(
            (
                dataset
                for dataset in self.datasets.values()
                if dataset.project_id == project_id and dataset.deleted_at is None
            ),
            key=lambda item: item.created_at,
            reverse=True,
        )

    async def save_dataset_profile(self, profile: DatasetProfile) -> DatasetProfile:
        self.dataset_profiles.setdefault(profile.dataset_id, []).append(profile)
        return profile

    async def list_dataset_profiles(self, *, project_id: str, dataset_id: str) -> list[DatasetProfile]:
        dataset = await self.get_dataset(project_id=project_id, dataset_id=dataset_id)
        if dataset is None:
            return []
        return list(self.dataset_profiles.get(dataset_id, []))

    async def get_dataset_profile(
        self, *, project_id: str, dataset_id: str, version: int
    ) -> DatasetProfile | None:
        profiles = await self.list_dataset_profiles(project_id=project_id, dataset_id=dataset_id)
        return next((profile for profile in profiles if profile.version == version), None)

    async def save_analysis_question(self, question: AnalysisQuestion) -> AnalysisQuestion:
        self.analysis_questions[question.question_id] = question
        return question

    async def get_analysis_question(
        self, *, project_id: str, dataset_id: str, question_id: str
    ) -> AnalysisQuestion | None:
        question = self.analysis_questions.get(question_id)
        if question is None or question.project_id != project_id or question.dataset_id != dataset_id:
            return None
        return question

    async def list_analysis_questions(
        self, *, project_id: str, dataset_id: str
    ) -> list[AnalysisQuestion]:
        return sorted(
            (
                question
                for question in self.analysis_questions.values()
                if question.project_id == project_id and question.dataset_id == dataset_id
            ),
            key=lambda question: question.created_at,
            reverse=True,
        )

    async def save_analysis_plan(self, plan: AnalysisPlanVersion) -> AnalysisPlanVersion:
        self.analysis_plans[(plan.plan_id, plan.version)] = plan
        return plan

    async def get_analysis_plan(
        self, *, project_id: str, plan_id: str, version: int
    ) -> AnalysisPlanVersion | None:
        plan = self.analysis_plans.get((plan_id, version))
        if plan is None or plan.project_id != project_id:
            return None
        return plan

    async def list_analysis_plans(
        self,
        *,
        project_id: str,
        dataset_id: str | None = None,
        plan_id: str | None = None,
    ) -> list[AnalysisPlanVersion]:
        return sorted(
            (
                plan
                for plan in self.analysis_plans.values()
                if plan.project_id == project_id
                and (dataset_id is None or plan.dataset_id == dataset_id)
                and (plan_id is None or plan.plan_id == plan_id)
            ),
            key=lambda plan: plan.created_at,
            reverse=True,
        )

    async def save_analysis_plan_decision(
        self, decision: AnalysisPlanDecision
    ) -> AnalysisPlanDecision:
        self.analysis_plan_decisions.append(decision)
        self.analysis_plan_decisions_by_idempotency[(decision.project_id, decision.idempotency_key)] = decision
        return decision

    async def commit_analysis_plan_review(
        self, plan: AnalysisPlanVersion, decision: AnalysisPlanDecision
    ) -> tuple[AnalysisPlanVersion, AnalysisPlanDecision]:
        existing = await self.get_analysis_plan_decision_by_idempotency(
            project_id=decision.project_id, idempotency_key=decision.idempotency_key
        )
        if existing is not None:
            existing_plan = await self.get_analysis_plan(
                project_id=existing.project_id,
                plan_id=existing.plan_id,
                version=existing.plan_version,
            )
            if existing_plan is None:
                raise KeyError(existing.plan_id)
            return existing_plan, existing
        await self.save_analysis_plan(plan)
        await self.save_analysis_plan_decision(decision)
        return plan, decision

    async def get_analysis_plan_decision_by_idempotency(
        self, *, project_id: str, idempotency_key: str
    ) -> AnalysisPlanDecision | None:
        return self.analysis_plan_decisions_by_idempotency.get((project_id, idempotency_key))

    async def list_analysis_plan_decisions(
        self, *, project_id: str, plan_id: str, version: int
    ) -> list[AnalysisPlanDecision]:
        return [
            decision
            for decision in self.analysis_plan_decisions
            if decision.project_id == project_id
            and decision.plan_id == plan_id
            and decision.plan_version == version
        ]

    async def save_analysis_code(self, code: AnalysisCodeVersion) -> AnalysisCodeVersion:
        self.analysis_code_versions[code.code_version_id] = code
        return code

    async def get_analysis_code(
        self, *, project_id: str, code_version_id: str
    ) -> AnalysisCodeVersion | None:
        code = self.analysis_code_versions.get(code_version_id)
        if code is None or code.project_id != project_id:
            return None
        return code

    async def list_analysis_codes_for_plan(
        self, *, project_id: str, plan_id: str, plan_version: int
    ) -> list[AnalysisCodeVersion]:
        return [
            code
            for code in self.analysis_code_versions.values()
            if code.project_id == project_id
            and code.plan_id == plan_id
            and code.plan_version == plan_version
        ]

    async def create_sandbox_run(self, run: SandboxRun) -> SandboxRun:
        existing = self.sandbox_runs_by_idempotency.get((run.project_id, run.idempotency_key))
        if existing is not None:
            return existing
        self.sandbox_runs[run.run_id] = run
        self.sandbox_runs_by_idempotency[(run.project_id, run.idempotency_key)] = run
        self.sandbox_run_status_history.extend(
            [
                SandboxRunStatusHistory(
                    run_id=run.run_id,
                    project_id=run.project_id,
                    to_status=SandboxRunStatus.PENDING_APPROVAL,
                    changed_by="control-plane",
                ),
                SandboxRunStatusHistory(
                    run_id=run.run_id,
                    project_id=run.project_id,
                    from_status=SandboxRunStatus.PENDING_APPROVAL,
                    to_status=run.status,
                    changed_by="control-plane",
                ),
            ]
        )
        return run

    async def get_sandbox_run(self, *, project_id: str, run_id: str) -> SandboxRun | None:
        run = self.sandbox_runs.get(run_id)
        if run is None or run.project_id != project_id:
            return None
        return run

    async def list_sandbox_runs(
        self, *, project_id: str, plan_id: str, plan_version: int
    ) -> list[SandboxRun]:
        return sorted(
            [
                run
                for run in self.sandbox_runs.values()
                if run.project_id == project_id
                and run.plan_id == plan_id
                and run.plan_version == plan_version
            ],
            key=lambda item: item.created_at,
        )

    async def get_sandbox_run_by_idempotency(self, *, project_id: str, idempotency_key: str) -> SandboxRun | None:
        return self.sandbox_runs_by_idempotency.get((project_id, idempotency_key))

    async def update_sandbox_run(self, run: SandboxRun, *, changed_by: str, reason: str | None = None) -> SandboxRun:
        previous = self.sandbox_runs.get(run.run_id)
        if previous is None:
            raise KeyError(run.run_id)
        self.sandbox_runs[run.run_id] = run
        if previous.status is not run.status:
            self.sandbox_run_status_history.append(
                SandboxRunStatusHistory(
                    run_id=run.run_id,
                    project_id=run.project_id,
                    from_status=previous.status,
                    to_status=run.status,
                    changed_by=changed_by,
                    reason=reason,
                )
            )
        return run

    async def claim_sandbox_run(self, *, worker_id: str, now, lease_seconds: int) -> SandboxRun | None:
        candidates = sorted(self.sandbox_runs.values(), key=lambda item: item.created_at)
        for run in candidates:
            reclaimable = run.status is SandboxRunStatus.RUNNING and run.lease_expires_at and run.lease_expires_at <= now
            if run.status is SandboxRunStatus.QUEUED or reclaimable:
                claimed = run.model_copy(
                    update={
                        "status": SandboxRunStatus.RUNNING,
                        "lease_owner": worker_id,
                        "lease_expires_at": now + timedelta(seconds=lease_seconds),
                        "updated_at": now,
                    }
                )
                return await self.update_sandbox_run(
                    claimed,
                    changed_by=worker_id,
                    reason="lease_reclaimed" if reclaimable else "lease_claimed",
                )
        return None

    async def renew_sandbox_run_lease(
        self, *, run_id: str, worker_id: str, now, lease_seconds: int
    ) -> bool:
        run = self.sandbox_runs.get(run_id)
        if (
            run is None
            or run.status is not SandboxRunStatus.RUNNING
            or run.lease_owner != worker_id
            or lease_seconds <= 0
        ):
            return False
        renewed = run.model_copy(
            update={
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "updated_at": now,
            }
        )
        self.sandbox_runs[run_id] = renewed
        self.sandbox_runs_by_idempotency[(run.project_id, run.idempotency_key)] = renewed
        return True

    async def consume_manifest_nonce(self, *, nonce: str, run_id: str) -> bool:
        owner = self.consumed_manifest_nonces.get(nonce)
        if owner is not None and owner != run_id:
            return False
        self.consumed_manifest_nonces[nonce] = run_id
        return True

    async def list_sandbox_run_status_history(
        self, *, project_id: str, run_id: str
    ) -> list[SandboxRunStatusHistory]:
        run = await self.get_sandbox_run(project_id=project_id, run_id=run_id)
        if run is None:
            return []
        return [
            item
            for item in self.sandbox_run_status_history
            if item.project_id == project_id and item.run_id == run_id
        ]

    async def save_artifact(self, artifact: AnalysisArtifact) -> AnalysisArtifact:
        self.analysis_artifacts.setdefault(artifact.run_id, []).append(artifact)
        return artifact

    async def list_artifacts(self, *, project_id: str, run_id: str) -> list[AnalysisArtifact]:
        run = await self.get_sandbox_run(project_id=project_id, run_id=run_id)
        return list(self.analysis_artifacts.get(run_id, [])) if run else []

    async def save_result_validation(self, validation: AnalysisResultValidation) -> AnalysisResultValidation:
        existing = self.result_validations.get(validation.run_id)
        return existing or self.result_validations.setdefault(validation.run_id, validation)

    async def get_result_validation(self, *, project_id: str, run_id: str) -> AnalysisResultValidation | None:
        run = await self.get_sandbox_run(project_id=project_id, run_id=run_id)
        return self.result_validations.get(run_id) if run else None

    async def save_result_interpretation(
        self, record: AnalysisResultInterpretationRecord
    ) -> AnalysisResultInterpretationRecord:
        existing = self.result_interpretations.get(record.run_id)
        return existing or self.result_interpretations.setdefault(record.run_id, record)

    async def get_result_interpretation(
        self, *, project_id: str, run_id: str
    ) -> AnalysisResultInterpretationRecord | None:
        run = await self.get_sandbox_run(project_id=project_id, run_id=run_id)
        return self.result_interpretations.get(run_id) if run else None

    async def save_analysis_citation(self, citation: AnalysisCitation) -> AnalysisCitation:
        existing = next(
            (item for item in self.analysis_citations.get(citation.run_id, []) if item.locator == citation.locator and item.value_hash == citation.value_hash),
            None,
        )
        if existing is not None:
            return existing
        self.analysis_citations.setdefault(citation.run_id, []).append(citation)
        return citation

    async def list_analysis_citations(self, *, project_id: str, run_id: str) -> list[AnalysisCitation]:
        run = await self.get_sandbox_run(project_id=project_id, run_id=run_id)
        return list(self.analysis_citations.get(run_id, [])) if run else []

    async def save_analysis_result_review(self, review: AnalysisResultReview) -> AnalysisResultReview:
        existing = self.analysis_result_reviews_by_idempotency.get((review.project_id, review.idempotency_key))
        if existing is not None:
            return existing
        self.analysis_result_reviews.append(review)
        self.analysis_result_reviews_by_idempotency[(review.project_id, review.idempotency_key)] = review
        return review

    async def commit_result_review(
        self,
        run: SandboxRun,
        review: AnalysisResultReview,
        *,
        changed_by: str,
        reason: str | None = None,
    ) -> tuple[SandboxRun, AnalysisResultReview]:
        existing = await self.get_analysis_result_review_by_idempotency(
            project_id=review.project_id, idempotency_key=review.idempotency_key
        )
        if existing is not None:
            existing_run = await self.get_sandbox_run(
                project_id=existing.project_id, run_id=existing.run_id
            )
            if existing_run is None:
                raise KeyError(existing.run_id)
            return existing_run, existing
        updated = await self.update_sandbox_run(
            run, changed_by=changed_by, reason=reason
        )
        await self.save_analysis_result_review(review)
        return updated, review

    async def get_analysis_result_review_by_idempotency(self, *, project_id: str, idempotency_key: str) -> AnalysisResultReview | None:
        return self.analysis_result_reviews_by_idempotency.get((project_id, idempotency_key))

    async def save_reproducibility_bundle(self, bundle: AnalysisReproducibilityBundle) -> AnalysisReproducibilityBundle:
        existing = self.reproducibility_bundles.get(bundle.run_id)
        return existing or self.reproducibility_bundles.setdefault(bundle.run_id, bundle)

    async def get_reproducibility_bundle(self, *, project_id: str, run_id: str) -> AnalysisReproducibilityBundle | None:
        run = await self.get_sandbox_run(project_id=project_id, run_id=run_id)
        return self.reproducibility_bundles.get(run_id) if run else None
