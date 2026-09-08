"""Validation-gated interpretation, append-only review, and reproducibility sealing."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Protocol
from uuid import uuid4

from sandbox_service.domain.analysis_plans import AnalysisPlanVersion
from sandbox_service.domain.datasets import DatasetProfile, DatasetRecord
from sandbox_service.domain.errors import (
    OutputValidationFailed,
    ReproducibilityBundleNotFound,
    ResultNotReviewable,
    SandboxRunNotFound,
)
from sandbox_service.domain.execution import AnalysisArtifact, AnalysisCodeVersion, SandboxRun, SandboxRunStatus
from sandbox_service.domain.ports import ProjectAIClient
from sandbox_service.domain.results import (
    AnalysisCitation,
    AnalysisReproducibilityBundle,
    AnalysisResultInterpretationRecord,
    AnalysisResultReview,
    AnalysisResultValidation,
    ResultInterpretation,
    ResultValidationStatus,
    ReviewAnalysisResultRequest,
)
from sandbox_service.execution.result_validator import ResultValidationError, ResultValidator, ValidatedResult


class ResultRepository(Protocol):
    async def get_sandbox_run(self, *, project_id: str, run_id: str) -> SandboxRun | None: ...
    async def update_sandbox_run(self, run: SandboxRun, *, changed_by: str, reason: str | None = None) -> SandboxRun: ...
    async def list_artifacts(self, *, project_id: str, run_id: str) -> list[AnalysisArtifact]: ...
    async def get_analysis_plan(self, *, project_id: str, plan_id: str, version: int) -> AnalysisPlanVersion | None: ...
    async def get_dataset(self, *, project_id: str, dataset_id: str, include_deleted: bool = False) -> DatasetRecord | None: ...
    async def get_dataset_profile(self, *, project_id: str, dataset_id: str, version: int) -> DatasetProfile | None: ...
    async def get_analysis_code(self, *, project_id: str, code_version_id: str) -> AnalysisCodeVersion | None: ...
    async def save_result_validation(self, validation: AnalysisResultValidation) -> AnalysisResultValidation: ...
    async def get_result_validation(self, *, project_id: str, run_id: str) -> AnalysisResultValidation | None: ...
    async def save_analysis_citation(self, citation: AnalysisCitation) -> AnalysisCitation: ...
    async def list_analysis_citations(self, *, project_id: str, run_id: str) -> list[AnalysisCitation]: ...
    async def save_result_interpretation(
        self, interpretation: AnalysisResultInterpretationRecord
    ) -> AnalysisResultInterpretationRecord: ...
    async def get_result_interpretation(
        self, *, project_id: str, run_id: str
    ) -> AnalysisResultInterpretationRecord | None: ...
    async def save_analysis_result_review(self, review: AnalysisResultReview) -> AnalysisResultReview: ...
    async def commit_result_review(
        self,
        run: SandboxRun,
        review: AnalysisResultReview,
        *,
        changed_by: str,
        reason: str | None = None,
    ) -> tuple[SandboxRun, AnalysisResultReview]: ...
    async def get_analysis_result_review_by_idempotency(self, *, project_id: str, idempotency_key: str) -> AnalysisResultReview | None: ...
    async def save_reproducibility_bundle(self, bundle: AnalysisReproducibilityBundle) -> AnalysisReproducibilityBundle: ...
    async def get_reproducibility_bundle(self, *, project_id: str, run_id: str) -> AnalysisReproducibilityBundle | None: ...


class ResultObjectStore(Protocol):
    async def get_bytes(self, *, key: str) -> bytes: ...


class ResultReviewService:
    """Keeps validation deterministic and makes AI interpretation an opt-in second step."""

    def __init__(
        self,
        *,
        repository: ResultRepository,
        object_store: ResultObjectStore,
        ai_client: ProjectAIClient | None = None,
        validator: ResultValidator | None = None,
    ) -> None:
        self._repository = repository
        self._object_store = object_store
        self._ai_client = ai_client
        self._validator = validator or ResultValidator()

    async def validate_run(self, *, project_id: str, run_id: str) -> AnalysisResultValidation:
        existing = await self._repository.get_result_validation(project_id=project_id, run_id=run_id)
        if existing is not None:
            return existing
        run = await self._require_run(project_id=project_id, run_id=run_id)
        if run.status is not SandboxRunStatus.COMPLETED_UNVALIDATED:
            raise ResultNotReviewable("Only completed_unvalidated runs can be validated")
        plan, profile, artifacts, result_artifact = await self._inputs_for_run(run)
        raw = await self._object_store.get_bytes(key=result_artifact.storage_key)
        try:
            if hashlib.sha256(raw).hexdigest() != result_artifact.content_hash:
                raise ResultValidationError(["analysis_result.json content hash does not match collected artifact metadata"])
            validated = self._validator.validate(
                raw_result=raw,
                plan=plan,
                profile=profile,
                artifact_filenames={artifact.filename for artifact in artifacts},
            )
        except ResultValidationError as exc:
            failed = await self._repository.save_result_validation(
                AnalysisResultValidation(
                    project_id=project_id,
                    run_id=run_id,
                    status=ResultValidationStatus.FAILED,
                    errors=exc.errors,
                )
            )
            await self._repository.update_sandbox_run(
                run.model_copy(update={"status": SandboxRunStatus.VALIDATION_FAILED, "error_code": "OUTPUT_VALIDATION_FAILED"}),
                changed_by="result-validator",
                reason="OUTPUT_VALIDATION_FAILED",
            )
            return failed
        validation = await self._repository.save_result_validation(
            AnalysisResultValidation(
                project_id=project_id,
                run_id=run_id,
                result_hash=validated.result_hash,
                status=ResultValidationStatus.VALIDATED,
                warnings=list(validated.warnings),
            )
        )
        await self._seal_bundle(
            run=run, plan=plan, profile=profile, artifacts=artifacts, result_hash=validated.result_hash
        )
        await self._repository.update_sandbox_run(
            run.model_copy(update={"status": SandboxRunStatus.RESULT_REVIEW_WAITING}),
            changed_by="result-validator",
            reason="OUTPUT_VALIDATED",
        )
        return validation

    async def interpret_validated(
        self, *, project_id: str, run_id: str, correlation_id: str | None = None
    ) -> tuple[AnalysisResultInterpretationRecord, list[AnalysisCitation]]:
        """Call ProjectAI only after a persisted successful validation."""
        validation = await self._repository.get_result_validation(project_id=project_id, run_id=run_id)
        if validation is None or validation.status is not ResultValidationStatus.VALIDATED:
            raise OutputValidationFailed("Result failed validation; interpretation is blocked")
        existing = await self._repository.get_result_interpretation(
            project_id=project_id, run_id=run_id
        )
        if existing is not None:
            return (
                existing,
                await self._repository.list_analysis_citations(
                    project_id=project_id, run_id=run_id
                ),
            )
        if self._ai_client is None:
            raise ResultNotReviewable("Result interpretation AI is not configured")
        run = await self._require_run(project_id=project_id, run_id=run_id)
        plan, profile, artifacts, result_artifact = await self._inputs_for_run(run)
        raw = await self._object_store.get_bytes(key=result_artifact.storage_key)
        if hashlib.sha256(raw).hexdigest() != result_artifact.content_hash:
            raise OutputValidationFailed("analysis_result.json content hash no longer matches collected metadata")
        # Re-parse only after the validation gate; this is the safe, structured output.
        validated = self._validator.validate(
            raw_result=raw,
            plan=plan,
            profile=profile,
            artifact_filenames={artifact.filename for artifact in artifacts},
        )
        input_payload: dict[str, Any] = {
            "validated_result": validated.result.model_dump(mode="json"),
            "approved_plan": {
                "plan_id": plan.plan_id,
                "version": plan.version,
                "objective": plan.objective.value,
                "method": plan.method,
                "limitations": plan.limitations,
            },
            "output_language": plan.output_language,
            "instruction": (
                "Use association language only unless the approved plan establishes "
                "causality. Do not put numbers in narrative; use numeric_claims. Every "
                "numeric_claim locator must be a JSON pointer to an exact numeric scalar "
                "inside validated_result, and value must equal that scalar."
            ),
        }
        request_correlation_id = correlation_id or str(uuid4())
        for attempt in range(2):
            generated = await self._ai_client.invoke_structured(
                project_id=project_id,
                operation="result_interpretation",
                prompt_version="analysis.result_interpretation.v1",
                input_payload=input_payload,
                output_schema=ResultInterpretation,
                correlation_id=request_correlation_id,
            )
            interpretation = ResultInterpretation.model_validate(generated)
            try:
                self._ensure_interpretation_safe(
                    interpretation=interpretation, objective=plan.objective.value
                )
                citations = await self._create_citations(
                    interpretation=interpretation,
                    run=run,
                    plan=plan,
                    profile=profile,
                    result_artifact=result_artifact,
                    result=validated,
                )
            except OutputValidationFailed as error:
                if attempt == 1:
                    raise
                input_payload = {
                    **input_payload,
                    "revision": {
                        "validation_error": str(error),
                        "previous_interpretation": interpretation.model_dump(mode="json"),
                        "instruction": (
                            "Correct the previous interpretation. Use only locators that "
                            "resolve to numeric scalars in validated_result and copy each "
                            "scalar exactly into value."
                        ),
                    },
                }
                continue
            saved = await self._repository.save_result_interpretation(
                AnalysisResultInterpretationRecord(
                    project_id=project_id,
                    run_id=run_id,
                    validation_id=validation.validation_id,
                    narrative=interpretation.narrative,
                    numeric_claims=interpretation.numeric_claims,
                    limitations=interpretation.limitations,
                    citation_ids=[citation.citation_id for citation in citations],
                )
            )
            return saved, citations
        raise RuntimeError("interpretation revision loop exhausted")

    async def review_result(
        self,
        *,
        project_id: str,
        run_id: str,
        reviewer_id: str,
        idempotency_key: str,
        request: ReviewAnalysisResultRequest,
    ) -> tuple[SandboxRun, AnalysisResultReview]:
        existing = await self._repository.get_analysis_result_review_by_idempotency(
            project_id=project_id, idempotency_key=idempotency_key
        )
        if existing is not None:
            if (
                existing.run_id != run_id
                or existing.decision is not request.decision
                or existing.comment != request.comment
            ):
                raise ResultNotReviewable(
                    "Idempotency-Key was already used for a different result review request"
                )
            return await self._require_run(project_id=project_id, run_id=existing.run_id), existing
        run = await self._require_run(project_id=project_id, run_id=run_id)
        validation = await self._repository.get_result_validation(project_id=project_id, run_id=run_id)
        if run.status is not SandboxRunStatus.RESULT_REVIEW_WAITING or validation is None or validation.status is not ResultValidationStatus.VALIDATED:
            raise ResultNotReviewable("Only validated results awaiting review can be reviewed")
        review = AnalysisResultReview(
            project_id=project_id,
            run_id=run_id,
            validation_id=validation.validation_id,
            reviewer_id=reviewer_id,
            decision=request.decision,
            comment=request.comment,
            idempotency_key=idempotency_key,
        )
        return await self._repository.commit_result_review(
            run.model_copy(update={"status": SandboxRunStatus(request.decision.value)}),
            review,
            changed_by=reviewer_id,
            reason=f"result_{request.decision.value}",
        )

    async def get_bundle(self, *, project_id: str, run_id: str) -> AnalysisReproducibilityBundle:
        await self._require_run(project_id=project_id, run_id=run_id)
        bundle = await self._repository.get_reproducibility_bundle(project_id=project_id, run_id=run_id)
        if bundle is None:
            raise ReproducibilityBundleNotFound("No sealed bundle exists for this run")
        return bundle

    async def _inputs_for_run(
        self, run: SandboxRun
    ) -> tuple[AnalysisPlanVersion, DatasetProfile, list[AnalysisArtifact], AnalysisArtifact]:
        plan = await self._repository.get_analysis_plan(project_id=run.project_id, plan_id=run.plan_id, version=run.plan_version)
        if plan is None:
            raise ResultNotReviewable("Pinned analysis plan is unavailable")
        profile = await self._repository.get_dataset_profile(project_id=run.project_id, dataset_id=run.dataset_id, version=plan.profile_version)
        if profile is None:
            raise ResultNotReviewable("Pinned dataset profile is unavailable")
        artifacts = await self._repository.list_artifacts(project_id=run.project_id, run_id=run.run_id)
        result_artifact = next((item for item in artifacts if item.artifact_type == "result" and item.filename == "analysis_result.json"), None)
        if result_artifact is None:
            raise OutputValidationFailed("analysis_result.json was not collected")
        return plan, profile, artifacts, result_artifact

    async def _require_run(self, *, project_id: str, run_id: str) -> SandboxRun:
        run = await self._repository.get_sandbox_run(project_id=project_id, run_id=run_id)
        if run is None:
            raise SandboxRunNotFound("Sandbox run was not found in this project")
        return run

    async def _create_citations(
        self,
        *,
        interpretation: ResultInterpretation,
        run: SandboxRun,
        plan: AnalysisPlanVersion,
        profile: DatasetProfile,
        result_artifact: AnalysisArtifact,
        result: ValidatedResult,
    ) -> list[AnalysisCitation]:
        pending: list[AnalysisCitation] = []
        payload = result.result.model_dump(mode="json")
        for claim in interpretation.numeric_claims:
            observed = self._json_pointer(payload, claim.locator)
            if observed != claim.value:
                raise OutputValidationFailed("A numeric claim does not match its result locator")
            pending.append(AnalysisCitation(
                project_id=run.project_id,
                dataset_id=run.dataset_id,
                dataset_hash=run.manifest.dataset_content_hash,
                profile_version=profile.version,
                plan_id=plan.plan_id,
                plan_version=plan.version,
                run_id=run.run_id,
                artifact_id=result_artifact.artifact_id,
                artifact_type=result_artifact.artifact_type,
                locator=claim.locator,
                value_hash=self._value_hash(observed),
            ))
        return [
            await self._repository.save_analysis_citation(citation)
            for citation in pending
        ]

    async def _seal_bundle(
        self, *, run: SandboxRun, plan: AnalysisPlanVersion, profile: DatasetProfile, artifacts: list[AnalysisArtifact], result_hash: str
    ) -> AnalysisReproducibilityBundle:
        existing = await self._repository.get_reproducibility_bundle(project_id=run.project_id, run_id=run.run_id)
        if existing is not None:
            return existing
        code = await self._repository.get_analysis_code(project_id=run.project_id, code_version_id=run.code_version_id)
        if code is None:
            raise ResultNotReviewable("Pinned code version is unavailable")
        canonical = {
            "run_id": run.run_id,
            "dataset_hash": run.manifest.dataset_content_hash,
            "profile_hash": profile.profile_hash,
            "research_context_hash": plan.context_hash,
            "plan_hash": plan.plan_hash,
            "plan_decision_id": run.plan_decision_id,
            "code_hash": code.code_hash,
            "prompt_version": code.prompt_version,
            "model_route_audit_id": self._model_route_audit_id(code),
            "image_digest": run.manifest.image_digest,
            "package_manifest_hash": run.manifest.package_manifest_hash,
            "random_seed": run.manifest.random_seed,
            "result_hash": result_hash,
            "artifact_hashes": sorted(item.content_hash for item in artifacts),
        }
        bundle = AnalysisReproducibilityBundle(
            project_id=run.project_id,
            run_id=run.run_id,
            dataset_hash=run.manifest.dataset_content_hash,
            profile_hash=profile.profile_hash,
            research_context_hash=plan.context_hash,
            plan_hash=plan.plan_hash,
            plan_decision_id=run.plan_decision_id,
            action_proposal_id=run.manifest.action_proposal_id,
            code_hash=code.code_hash,
            prompt_version=code.prompt_version,
            model_route_audit_id=canonical["model_route_audit_id"],
            image_digest=run.manifest.image_digest,
            package_manifest_hash=run.manifest.package_manifest_hash,
            random_seed=run.manifest.random_seed,
            result_hash=result_hash,
            artifact_hashes=canonical["artifact_hashes"],
            bundle_hash=self._value_hash(canonical),
        )
        return await self._repository.save_reproducibility_bundle(bundle)

    @staticmethod
    def _ensure_interpretation_safe(*, interpretation: ResultInterpretation, objective: str) -> None:
        numeric = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")
        causal = re.compile(r"\b(caus(?:e|es|ed|al)|caused by|leads? to|drives?)\b", re.IGNORECASE)
        if any(numeric.search(text) for text in interpretation.narrative):
            raise OutputValidationFailed("Numeric narrative must be emitted as a cited numeric_claim")
        if objective == "associate" and any(causal.search(text) for text in interpretation.narrative):
            raise OutputValidationFailed("Association interpretation must not claim causality")

    @staticmethod
    def _json_pointer(payload: Any, locator: str) -> Any:
        current = payload
        for part in locator.lstrip("/").split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, list):
                try:
                    current = current[int(key)]
                except (ValueError, IndexError) as exc:
                    raise OutputValidationFailed("Numeric claim locator is invalid") from exc
            elif isinstance(current, dict) and key in current:
                current = current[key]
            else:
                raise OutputValidationFailed("Numeric claim locator is invalid")
        if not isinstance(current, (int, float)) or isinstance(current, bool):
            raise OutputValidationFailed("Numeric claim locator does not resolve to a number")
        return current

    @staticmethod
    def _value_hash(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()

    @staticmethod
    def _model_route_audit_id(code: AnalysisCodeVersion) -> str:
        return "route_" + hashlib.sha256(f"{code.prompt_version}:{code.code_hash}".encode("utf-8")).hexdigest()
