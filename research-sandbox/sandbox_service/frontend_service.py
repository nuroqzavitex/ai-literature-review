"""Read-only project-scoped query facade used by browser-facing routers."""

from __future__ import annotations

import hashlib
from typing import Protocol

from sandbox_service.domain.analysis_plans import AnalysisPlanDecision, AnalysisPlanVersion
from sandbox_service.domain.datasets import AnalysisQuestion, DatasetRecord
from sandbox_service.domain.errors import (
    AnalysisCodeNotFound,
    AnalysisArtifactNotFound,
    AnalysisPlanNotFound,
    AnalysisQuestionNotFound,
    DatasetNotFound,
    OutputValidationFailed,
    ResultInterpretationNotFound,
    ResultValidationNotFound,
    SandboxRunNotFound,
)
from sandbox_service.domain.execution import AnalysisArtifact, AnalysisCodeVersion, SandboxRun, SandboxRunStatusHistory
from sandbox_service.domain.frontend import AnalysisArtifactSummary, PublicAnalysisCode
from sandbox_service.domain.results import (
    AnalysisCitation,
    AnalysisResultInterpretationRecord,
    AnalysisResultValidation,
)


class FrontendQueryRepository(Protocol):
    async def get_dataset(
        self, *, project_id: str, dataset_id: str, include_deleted: bool = False
    ) -> DatasetRecord | None: ...

    async def list_analysis_questions(
        self, *, project_id: str, dataset_id: str
    ) -> list[AnalysisQuestion]: ...

    async def get_analysis_question(
        self, *, project_id: str, dataset_id: str, question_id: str
    ) -> AnalysisQuestion | None: ...

    async def list_analysis_plans(
        self, *, project_id: str, dataset_id: str | None = None, plan_id: str | None = None
    ) -> list[AnalysisPlanVersion]: ...

    async def get_analysis_plan(
        self, *, project_id: str, plan_id: str, version: int
    ) -> AnalysisPlanVersion | None: ...

    async def list_analysis_plan_decisions(
        self, *, project_id: str, plan_id: str, version: int
    ) -> list[AnalysisPlanDecision]: ...

    async def get_sandbox_run(self, *, project_id: str, run_id: str) -> SandboxRun | None: ...

    async def list_sandbox_runs(
        self, *, project_id: str, plan_id: str, plan_version: int
    ) -> list[SandboxRun]: ...

    async def list_sandbox_run_status_history(
        self, *, project_id: str, run_id: str
    ) -> list[SandboxRunStatusHistory]: ...

    async def get_analysis_code(
        self, *, project_id: str, code_version_id: str
    ) -> AnalysisCodeVersion | None: ...

    async def list_artifacts(self, *, project_id: str, run_id: str) -> list[AnalysisArtifact]: ...

    async def get_result_validation(
        self, *, project_id: str, run_id: str
    ) -> AnalysisResultValidation | None: ...

    async def get_result_interpretation(
        self, *, project_id: str, run_id: str
    ) -> AnalysisResultInterpretationRecord | None: ...

    async def list_analysis_citations(
        self, *, project_id: str, run_id: str
    ) -> list[AnalysisCitation]: ...


class FrontendObjectStore(Protocol):
    async def get_bytes(self, *, key: str) -> bytes: ...


class FrontendQueryService:
    def __init__(
        self, *, repository: FrontendQueryRepository, object_store: FrontendObjectStore
    ) -> None:
        self._repository = repository
        self._object_store = object_store

    async def list_questions(self, *, project_id: str, dataset_id: str) -> list[AnalysisQuestion]:
        await self._require_dataset(project_id=project_id, dataset_id=dataset_id)
        return await self._repository.list_analysis_questions(
            project_id=project_id, dataset_id=dataset_id
        )

    async def get_question(
        self, *, project_id: str, dataset_id: str, question_id: str
    ) -> AnalysisQuestion:
        question = await self._repository.get_analysis_question(
            project_id=project_id, dataset_id=dataset_id, question_id=question_id
        )
        if question is None:
            raise AnalysisQuestionNotFound("Analysis question was not found in this project dataset")
        return question

    async def list_dataset_plans(
        self, *, project_id: str, dataset_id: str
    ) -> list[AnalysisPlanVersion]:
        await self._require_dataset(project_id=project_id, dataset_id=dataset_id)
        return await self._repository.list_analysis_plans(
            project_id=project_id, dataset_id=dataset_id
        )

    async def list_plan_versions(
        self, *, project_id: str, plan_id: str
    ) -> list[AnalysisPlanVersion]:
        plans = await self._repository.list_analysis_plans(
            project_id=project_id, plan_id=plan_id
        )
        if not plans:
            raise AnalysisPlanNotFound("Analysis plan was not found in this project")
        return sorted(plans, key=lambda item: item.version)

    async def list_plan_decisions(
        self, *, project_id: str, plan_id: str, version: int
    ) -> list[AnalysisPlanDecision]:
        if await self._repository.get_analysis_plan(
            project_id=project_id, plan_id=plan_id, version=version
        ) is None:
            raise AnalysisPlanNotFound("Analysis plan was not found in this project")
        return await self._repository.list_analysis_plan_decisions(
            project_id=project_id, plan_id=plan_id, version=version
        )

    async def list_run_status_history(
        self, *, project_id: str, run_id: str
    ) -> list[SandboxRunStatusHistory]:
        await self._require_run(project_id=project_id, run_id=run_id)
        return await self._repository.list_sandbox_run_status_history(
            project_id=project_id, run_id=run_id
        )

    async def list_runs(
        self, *, project_id: str, plan_id: str, plan_version: int
    ) -> list[SandboxRun]:
        if await self._repository.get_analysis_plan(
            project_id=project_id, plan_id=plan_id, version=plan_version
        ) is None:
            raise AnalysisPlanNotFound("Analysis plan was not found in this project")
        runs = await self._repository.list_sandbox_runs(
            project_id=project_id,
            plan_id=plan_id,
            plan_version=plan_version,
        )
        return sorted(runs, key=lambda item: item.created_at)

    async def list_artifacts(
        self, *, project_id: str, run_id: str
    ) -> list[AnalysisArtifactSummary]:
        await self._require_run(project_id=project_id, run_id=run_id)
        artifacts = await self._repository.list_artifacts(project_id=project_id, run_id=run_id)
        return [
            AnalysisArtifactSummary(
                artifact_id=item.artifact_id,
                run_id=item.run_id,
                artifact_type=item.artifact_type,
                filename=item.filename,
                content_hash=item.content_hash,
                size_bytes=item.size_bytes,
                download_url=(
                    f"/api/v1/projects/{project_id}/sandbox-runs/{run_id}"
                    f"/artifacts/{item.artifact_id}/content"
                ),
            )
            for item in artifacts
        ]

    async def get_run_code(self, *, project_id: str, run_id: str) -> PublicAnalysisCode:
        run = await self._require_run(project_id=project_id, run_id=run_id)
        code = await self._repository.get_analysis_code(
            project_id=project_id, code_version_id=run.code_version_id
        )
        if code is None or code.code_version_id != run.code_version_id:
            raise AnalysisCodeNotFound("Generated Python code was not found for this project run")
        return PublicAnalysisCode.from_domain(run=run, code=code)

    async def get_artifact_content(
        self, *, project_id: str, run_id: str, artifact_id: str
    ) -> tuple[AnalysisArtifact, bytes]:
        await self._require_run(project_id=project_id, run_id=run_id)
        artifacts = await self._repository.list_artifacts(project_id=project_id, run_id=run_id)
        artifact = next((item for item in artifacts if item.artifact_id == artifact_id), None)
        if artifact is None:
            raise AnalysisArtifactNotFound("Analysis artifact was not found in this project run")
        content = await self._object_store.get_bytes(key=artifact.storage_key)
        if len(content) != artifact.size_bytes or hashlib.sha256(content).hexdigest() != artifact.content_hash:
            raise OutputValidationFailed("Stored artifact no longer matches its immutable metadata")
        return artifact, content

    async def get_validation(
        self, *, project_id: str, run_id: str
    ) -> AnalysisResultValidation:
        await self._require_run(project_id=project_id, run_id=run_id)
        validation = await self._repository.get_result_validation(
            project_id=project_id, run_id=run_id
        )
        if validation is None:
            raise ResultValidationNotFound("No result validation exists for this run")
        return validation

    async def get_interpretation(
        self, *, project_id: str, run_id: str
    ) -> AnalysisResultInterpretationRecord:
        await self._require_run(project_id=project_id, run_id=run_id)
        interpretation = await self._repository.get_result_interpretation(
            project_id=project_id, run_id=run_id
        )
        if interpretation is None:
            raise ResultInterpretationNotFound("No validated result interpretation exists for this run")
        return interpretation

    async def list_citations(
        self, *, project_id: str, run_id: str
    ) -> list[AnalysisCitation]:
        await self._require_run(project_id=project_id, run_id=run_id)
        return await self._repository.list_analysis_citations(
            project_id=project_id, run_id=run_id
        )

    async def _require_dataset(self, *, project_id: str, dataset_id: str) -> DatasetRecord:
        dataset = await self._repository.get_dataset(project_id=project_id, dataset_id=dataset_id)
        if dataset is None:
            raise DatasetNotFound("Dataset was not found in this project")
        return dataset

    async def _require_run(self, *, project_id: str, run_id: str) -> SandboxRun:
        run = await self._repository.get_sandbox_run(project_id=project_id, run_id=run_id)
        if run is None:
            raise SandboxRunNotFound("Sandbox run was not found in this project")
        return run
