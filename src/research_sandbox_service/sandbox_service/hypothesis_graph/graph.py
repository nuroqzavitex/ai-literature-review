"""Explicit, AI-assisted draft generation from a pinned context only."""

from typing import Any, Protocol
from uuid import uuid4

from sandbox_service.domain.errors import SandboxModeMismatch, SandboxSessionNotFound
from sandbox_service.domain.hypotheses import (
    EvidenceStatus,
    ExperimentDraft,
    ExperimentDraftContent,
    HypothesisDraft,
    HypothesisDraftContent,
    DraftStatus,
    ReviewHypothesisDraftRequest,
)
from sandbox_service.domain.ports import ProjectAIClient
from sandbox_service.domain.sessions import (
    ResearchContextSnapshot,
    SandboxMode,
    SandboxSessionResponse,
)


class HypothesisRepository(Protocol):
    async def get_session(
        self, *, project_id: str, session_id: str
    ) -> SandboxSessionResponse | None: ...

    async def get_context_snapshot(self, *, context_id: str) -> ResearchContextSnapshot | None: ...

    async def save_hypothesis(self, draft: HypothesisDraft) -> HypothesisDraft: ...

    async def get_hypothesis(
        self, *, project_id: str, session_id: str, hypothesis_id: str
    ) -> HypothesisDraft | None: ...

    async def list_hypotheses(
        self, *, project_id: str, session_id: str
    ) -> list[HypothesisDraft]: ...

    async def save_experiment(self, draft: ExperimentDraft) -> ExperimentDraft: ...

    async def get_experiment(
        self, *, project_id: str, session_id: str, experiment_id: str
    ) -> ExperimentDraft | None: ...

    async def list_experiments(
        self, *, project_id: str, session_id: str
    ) -> list[ExperimentDraft]: ...


class HypothesisSandboxGraph:
    """Creates immutable draft versions; it does not publish conclusions or run code."""

    def __init__(self, *, repository: HypothesisRepository, ai_client: ProjectAIClient) -> None:
        self._repository = repository
        self._ai_client = ai_client

    async def generate_hypothesis(
        self,
        *,
        project_id: str,
        session_id: str,
        actor_id: str,
        question: str | None = None,
        output_language: str = "vi",
        correlation_id: str | None = None,
    ) -> HypothesisDraft:
        session, context = await self._load_hypothesis_session(
            project_id=project_id, session_id=session_id
        )
        resolved_question = question or session.initial_question
        if not resolved_question and context:
            resolved_question = context.research_question_suggestion
        if not resolved_question:
            raise ValueError("A research question is required to draft a hypothesis")

        payload = {
            "research_question": resolved_question,
            "context": self._context_payload(context),
            "output_language": output_language,
            "instruction": "Produce a falsifiable draft, not a scientific fact.",
        }
        generated = await self._ai_client.invoke_structured(
            project_id=project_id,
            operation="hypothesis_generation",
            prompt_version="sandbox.hypothesis_generation.v1",
            input_payload=payload,
            output_schema=HypothesisDraftContent,
            correlation_id=correlation_id or str(uuid4()),
        )
        content = HypothesisDraftContent.model_validate(generated)
        evidence_status = self._evidence_status(context)
        limitations = list(content.limitations)
        if evidence_status is not EvidenceStatus.VERIFIED:
            limitations.append(
                "Bằng chứng của bản thảo chưa được xác minh; không được trình bày nội dung này như một sự thật."
                if output_language == "vi"
                else "Evidence is not verified for this draft; it must not be presented as a fact."
            )
        draft_payload = content.model_dump()
        draft_payload["limitations"] = limitations
        return await self._repository.save_hypothesis(
            HypothesisDraft(
                **draft_payload,
                session_id=session_id,
                evidence_status=evidence_status,
            )
        )

    async def generate_experiment(
        self,
        *,
        project_id: str,
        session_id: str,
        hypothesis_id: str,
        actor_id: str,
        output_language: str = "vi",
        correlation_id: str | None = None,
    ) -> ExperimentDraft:
        session, context = await self._load_hypothesis_session(
            project_id=project_id, session_id=session_id
        )
        hypothesis = await self._repository.get_hypothesis(
            project_id=project_id, session_id=session_id, hypothesis_id=hypothesis_id
        )
        if hypothesis is None:
            raise SandboxSessionNotFound("Hypothesis draft was not found in this project session")

        generated = await self._ai_client.invoke_structured(
            project_id=project_id,
            operation="experiment_design",
            prompt_version="sandbox.experiment_design.v1",
            input_payload={
                "hypothesis": hypothesis.model_dump(mode="json"),
                "context": self._context_payload(context),
                "output_language": output_language,
                "instruction": "Produce a draft experiment with assumptions and risks; no execution.",
            },
            output_schema=ExperimentDraftContent,
            correlation_id=correlation_id or str(uuid4()),
        )
        content = ExperimentDraftContent.model_validate(generated)
        return await self._repository.save_experiment(
            ExperimentDraft(
                **content.model_dump(), session_id=session_id, hypothesis_id=hypothesis.hypothesis_id
            )
        )

    async def review_hypothesis(
        self,
        *,
        project_id: str,
        session_id: str,
        hypothesis_id: str,
        reviewer_id: str,
        request: ReviewHypothesisDraftRequest,
    ) -> HypothesisDraft:
        await self._load_hypothesis_session(project_id=project_id, session_id=session_id)
        hypothesis = await self._repository.get_hypothesis(
            project_id=project_id, session_id=session_id, hypothesis_id=hypothesis_id
        )
        if hypothesis is None:
            raise SandboxSessionNotFound("Hypothesis draft was not found in this project session")
        if hypothesis.status is not DraftStatus.DRAFT:
            raise ValueError("Only a draft hypothesis can be reviewed once")
        return await self._repository.save_hypothesis(
            hypothesis.model_copy(update={"status": DraftStatus(request.decision)})
        )

    async def list_hypotheses(self, *, project_id: str, session_id: str) -> list[HypothesisDraft]:
        await self._load_hypothesis_session(project_id=project_id, session_id=session_id)
        return await self._repository.list_hypotheses(project_id=project_id, session_id=session_id)

    async def list_experiments(self, *, project_id: str, session_id: str) -> list[ExperimentDraft]:
        await self._load_hypothesis_session(project_id=project_id, session_id=session_id)
        return await self._repository.list_experiments(project_id=project_id, session_id=session_id)

    async def get_experiment(
        self, *, project_id: str, session_id: str, experiment_id: str
    ) -> ExperimentDraft:
        await self._load_hypothesis_session(project_id=project_id, session_id=session_id)
        experiment = await self._repository.get_experiment(
            project_id=project_id, session_id=session_id, experiment_id=experiment_id
        )
        if experiment is None:
            raise SandboxSessionNotFound("Experiment draft was not found in this project session")
        return experiment

    async def _load_hypothesis_session(
        self, *, project_id: str, session_id: str
    ) -> tuple[SandboxSessionResponse, ResearchContextSnapshot | None]:
        session = await self._repository.get_session(project_id=project_id, session_id=session_id)
        if session is None:
            raise SandboxSessionNotFound("Sandbox session was not found in this project")
        if session.mode is not SandboxMode.HYPOTHESIS:
            raise SandboxModeMismatch("Hypothesis drafting requires a hypothesis-mode session")
        context = None
        if session.context_snapshot_id:
            context = await self._repository.get_context_snapshot(
                context_id=session.context_snapshot_id
            )
        return session, context

    @staticmethod
    def _context_payload(context: ResearchContextSnapshot | None) -> dict[str, Any] | None:
        if context is None:
            return None
        # Context contains references and limitations only; raw source material is not copied.
        return {
            "context_id": context.context_id,
            "content_hash": context.content_hash,
            "source_status": context.source_status,
            "evidence_refs": context.evidence_refs,
            "limitations": context.limitations,
            "method_suggestions": context.method_suggestions,
        }

    @staticmethod
    def _evidence_status(context: ResearchContextSnapshot | None) -> EvidenceStatus:
        if context is None:
            return EvidenceStatus.UNVERIFIED
        value = context.source_status.lower()
        if value in {"reviewed", "validated", "verified"}:
            return EvidenceStatus.VERIFIED
        if value in {"insufficient", "insufficient_evidence"}:
            return EvidenceStatus.INSUFFICIENT
        return EvidenceStatus.UNVERIFIED
