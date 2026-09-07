"""PostgreSQL-backed repository for the Sandbox control plane.

The domain services deliberately depend on structural protocols rather than on
SQLAlchemy.  This adapter implements the same async surface as the in-memory
repository while keeping database concerns (UUID coercion, upserts, leases and
idempotency) at this boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable
from datetime import timedelta
from typing import Any, TypeVar
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from sandbox_service.domain.adoption import AdoptionDecision, AdoptionProposal
from sandbox_service.domain.analysis_plans import AnalysisPlanDecision, AnalysisPlanVersion
from sandbox_service.domain.datasets import AnalysisQuestion, DatasetProfile, DatasetRecord
from sandbox_service.domain.execution import (
    AnalysisArtifact,
    AnalysisCodeVersion,
    SandboxExecutionManifest,
    SandboxRun,
    SandboxRunStatus,
    SandboxRunStatusHistory,
)
from sandbox_service.domain.graph_overlays import GraphOverlay, GraphOverlayOperation, OverlayAssessment
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

ModelT = TypeVar("ModelT", bound=BaseModel)


class SandboxSchemaUnavailable(RuntimeError):
    """Raised when the independent sandbox migration chain is not at the required schema."""


class PostgresSandboxRepository:
    """Durable repository using the tables owned by migrations ``s0001+``."""

    REQUIRED_TABLES = {
        "research_sandbox_context_snapshots",
        "research_sandbox_sessions",
        "research_sandbox_session_status_history",
        "sandbox_hypothesis_versions",
        "sandbox_experiment_versions",
        "sandbox_graph_overlays",
        "sandbox_graph_overlay_operations",
        "sandbox_overlay_assessments",
        "sandbox_adoption_proposals",
        "sandbox_adoption_decisions",
        "analysis_datasets",
        "analysis_dataset_profiles",
        "analysis_questions",
        "analysis_plan_versions",
        "analysis_plan_decisions",
        "analysis_code_versions",
        "sandbox_runs",
        "sandbox_run_status_history",
        "sandbox_manifest_nonces",
        "sandbox_service_auth_nonces",
        "analysis_artifacts",
        "analysis_result_validations",
        "analysis_result_interpretations",
        "analysis_result_reviews",
        "analysis_citations",
        "analysis_reproducibility_bundles",
    }

    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 10,
        max_overflow: int = 10,
        pool_timeout_seconds: float = 10.0,
    ) -> None:
        if not database_url.startswith(("postgresql+psycopg://", "postgresql+psycopg_async://")):
            raise ValueError("PostgresSandboxRepository requires a postgresql+psycopg URL")
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout_seconds,
        )
        self._metadata = sa.MetaData()
        self._schema_lock = asyncio.Lock()
        self._schema_ready = False

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def ping(self) -> None:
        await self._ensure_schema()
        async with self.engine.connect() as connection:
            await connection.execute(sa.text("SELECT 1"))

    async def ready(self) -> bool:
        try:
            await self.ping()
        except Exception:
            return False
        return True

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            async with self.engine.connect() as connection:
                await connection.run_sync(self._metadata.reflect)
            missing = sorted(self.REQUIRED_TABLES - set(self._metadata.tables))
            if missing:
                raise SandboxSchemaUnavailable(
                    "Sandbox database is not migrated to the required head; missing tables: "
                    + ", ".join(missing)
                )
            code_columns = self._metadata.tables["analysis_code_versions"].c
            if "source_code" not in code_columns or "revision_count" not in code_columns:
                raise SandboxSchemaUnavailable("Sandbox database must be upgraded through s0007")
            self._schema_ready = True

    async def _table(self, name: str) -> sa.Table:
        await self._ensure_schema()
        return self._metadata.tables[name]

    @staticmethod
    def _coerce(column: sa.Column[Any], value: Any) -> Any:
        if value is None:
            return None
        if isinstance(column.type, sa.Uuid) and not isinstance(value, UUID):
            return UUID(str(value))
        return value

    @classmethod
    def _typed_values(cls, table: sa.Table, values: dict[str, Any]) -> dict[str, Any]:
        return {
            key: cls._coerce(table.c[key], value)
            for key, value in values.items()
            if key in table.c
        }

    @staticmethod
    def _clean_row(row: sa.RowMapping | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}

    @classmethod
    def _model(cls, model: type[ModelT], row: sa.RowMapping, aliases: dict[str, str] | None = None) -> ModelT:
        clean = cls._clean_row(row) or {}
        for target, source in (aliases or {}).items():
            clean[target] = clean.get(source)
        fields = model.model_fields
        return model.model_validate({key: value for key, value in clean.items() if key in fields})

    @staticmethod
    def _hash(value: Any) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def _where(cls, table: sa.Table, **filters: Any) -> list[Any]:
        return [table.c[key] == cls._coerce(table.c[key], value) for key, value in filters.items()]

    async def _fetch_one(
        self,
        table_name: str,
        *,
        filters: dict[str, Any],
        order_by: Iterable[Any] = (),
    ) -> sa.RowMapping | None:
        table = await self._table(table_name)
        statement = sa.select(table).where(*self._where(table, **filters))
        if order_by:
            statement = statement.order_by(*order_by)
        async with self.engine.connect() as connection:
            return (await connection.execute(statement.limit(1))).mappings().first()

    async def _fetch_all(
        self,
        table_name: str,
        *,
        filters: dict[str, Any],
        order_by: Iterable[Any] = (),
    ) -> list[sa.RowMapping]:
        table = await self._table(table_name)
        statement = sa.select(table).where(*self._where(table, **filters))
        if order_by:
            statement = statement.order_by(*order_by)
        async with self.engine.connect() as connection:
            return list((await connection.execute(statement)).mappings().all())

    async def _upsert(
        self,
        table_name: str,
        values: dict[str, Any],
        *,
        conflict_columns: list[str],
        update_columns: Iterable[str],
    ) -> sa.RowMapping:
        table = await self._table(table_name)
        typed = self._typed_values(table, values)
        insert = pg_insert(table).values(**typed)
        updates = {name: insert.excluded[name] for name in update_columns if name in typed}
        if updates:
            statement = insert.on_conflict_do_update(
                index_elements=[table.c[name] for name in conflict_columns], set_=updates
            ).returning(table)
        else:
            statement = insert.on_conflict_do_nothing(
                index_elements=[table.c[name] for name in conflict_columns]
            ).returning(table)
        async with self.engine.begin() as connection:
            row = (await connection.execute(statement)).mappings().first()
            if row is not None:
                return row
            conflict_filter = {
                name: typed[name]
                for name in conflict_columns
            }
            return (
                await connection.execute(
                    sa.select(table).where(*self._where(table, **conflict_filter))
                )
            ).mappings().one()

    async def save_context_snapshot(self, snapshot: ResearchContextSnapshot) -> None:
        payload = snapshot.model_dump(mode="json")
        await self._upsert(
            "research_sandbox_context_snapshots",
            {
                "context_id": snapshot.context_id,
                "project_id": snapshot.project_id,
                "source_type": snapshot.source_type.value,
                "source_resource_id": snapshot.source_resource_id,
                "schema_version": snapshot.schema_version,
                "content_hash": snapshot.content_hash,
                "payload": payload,
                "created_at": snapshot.created_at,
            },
            conflict_columns=["context_id"],
            update_columns=[],
        )

    async def get_context_snapshot(self, *, context_id: str) -> ResearchContextSnapshot | None:
        row = await self._fetch_one(
            "research_sandbox_context_snapshots", filters={"context_id": context_id}
        )
        return ResearchContextSnapshot.model_validate(row["payload"]) if row else None

    async def create_session(self, session: SandboxSessionResponse) -> SandboxSessionResponse:
        sessions = await self._table("research_sandbox_sessions")
        history = await self._table("research_sandbox_session_status_history")
        values = self._typed_values(sessions, session.model_dump(mode="python"))
        async with self.engine.begin() as connection:
            inserted = (
                await connection.execute(
                    pg_insert(sessions).values(**values).on_conflict_do_nothing(
                        index_elements=[sessions.c.session_id]
                    ).returning(sessions)
                )
            ).mappings().first()
            if inserted is None:
                inserted = (
                    await connection.execute(
                        sa.select(sessions).where(sessions.c.session_id == self._coerce(sessions.c.session_id, session.session_id))
                    )
                ).mappings().one()
            else:
                await connection.execute(
                    sa.insert(history).values(
                        **self._typed_values(
                            history,
                            {
                                "history_id": str(uuid4()),
                                "session_id": session.session_id,
                                "project_id": session.project_id,
                                "from_status": None,
                                "to_status": session.status.value,
                                "changed_by": session.creator_id,
                                "reason": "session_created",
                                "created_at": session.created_at,
                            },
                        )
                    )
                )
        return self._model(SandboxSessionResponse, inserted)

    async def get_session(self, *, project_id: str, session_id: str) -> SandboxSessionResponse | None:
        row = await self._fetch_one(
            "research_sandbox_sessions", filters={"project_id": project_id, "session_id": session_id}
        )
        return self._model(SandboxSessionResponse, row) if row else None

    async def list_sessions(self, *, project_id: str) -> list[SandboxSessionResponse]:
        table = await self._table("research_sandbox_sessions")
        rows = await self._fetch_all(
            "research_sandbox_sessions",
            filters={"project_id": project_id},
            order_by=(table.c.created_at.desc(),),
        )
        return [self._model(SandboxSessionResponse, row) for row in rows]

    async def update_session_status(
        self,
        session: SandboxSessionResponse,
        *,
        changed_by: str,
        reason: str | None = None,
    ) -> SandboxSessionResponse:
        sessions = await self._table("research_sandbox_sessions")
        history = await self._table("research_sandbox_session_status_history")
        async with self.engine.begin() as connection:
            previous = (
                await connection.execute(
                    sa.select(sessions)
                    .where(
                        sessions.c.project_id == session.project_id,
                        sessions.c.session_id == self._coerce(sessions.c.session_id, session.session_id),
                    )
                    .with_for_update()
                )
            ).mappings().first()
            if previous is None:
                raise KeyError(session.session_id)
            row = (
                await connection.execute(
                    sa.update(sessions)
                    .where(sessions.c.session_id == previous["session_id"])
                    .values(status=session.status.value, updated_at=session.updated_at)
                    .returning(sessions)
                )
            ).mappings().one()
            if previous["status"] != session.status.value:
                await connection.execute(
                    sa.insert(history).values(
                        **self._typed_values(
                            history,
                            {
                                "history_id": str(uuid4()),
                                "session_id": session.session_id,
                                "project_id": session.project_id,
                                "from_status": previous["status"],
                                "to_status": session.status.value,
                                "changed_by": changed_by,
                                "reason": reason,
                                "created_at": session.updated_at,
                            },
                        )
                    )
                )
        return self._model(SandboxSessionResponse, row)

    async def list_session_status_history(
        self, *, project_id: str, session_id: str
    ) -> list[SandboxSessionStatusHistory]:
        table = await self._table("research_sandbox_session_status_history")
        rows = await self._fetch_all(
            "research_sandbox_session_status_history",
            filters={"project_id": project_id, "session_id": session_id},
            order_by=(table.c.created_at.asc(),),
        )
        return [self._model(SandboxSessionStatusHistory, row) for row in rows]

    async def save_hypothesis(self, draft: HypothesisDraft) -> HypothesisDraft:
        session = await self._session_for_id(draft.session_id)
        values = draft.model_dump(mode="python") | {
            "hypothesis_version_id": str(uuid4()),
            "project_id": session.project_id,
            "content_hash": self._hash(draft.model_dump(mode="json", exclude={"status", "created_at"})),
        }
        row = await self._upsert(
            "sandbox_hypothesis_versions",
            values,
            conflict_columns=["hypothesis_id", "version"],
            update_columns=["status"],
        )
        return self._model(HypothesisDraft, row)

    async def get_hypothesis(
        self, *, project_id: str, session_id: str, hypothesis_id: str
    ) -> HypothesisDraft | None:
        table = await self._table("sandbox_hypothesis_versions")
        row = await self._fetch_one(
            "sandbox_hypothesis_versions",
            filters={"project_id": project_id, "session_id": session_id, "hypothesis_id": hypothesis_id},
            order_by=(table.c.version.desc(),),
        )
        return self._model(HypothesisDraft, row) if row else None

    async def list_hypotheses(self, *, project_id: str, session_id: str) -> list[HypothesisDraft]:
        table = await self._table("sandbox_hypothesis_versions")
        rows = await self._fetch_all(
            "sandbox_hypothesis_versions",
            filters={"project_id": project_id, "session_id": session_id},
            order_by=(table.c.created_at.desc(),),
        )
        return [self._model(HypothesisDraft, row) for row in rows]

    async def save_experiment(self, draft: ExperimentDraft) -> ExperimentDraft:
        session = await self._session_for_id(draft.session_id)
        values = draft.model_dump(mode="python") | {
            "experiment_version_id": str(uuid4()),
            "project_id": session.project_id,
            "content_hash": self._hash(draft.model_dump(mode="json", exclude={"status", "created_at"})),
        }
        row = await self._upsert(
            "sandbox_experiment_versions",
            values,
            conflict_columns=["experiment_id", "version"],
            update_columns=["status"],
        )
        return self._model(ExperimentDraft, row)

    async def get_experiment(
        self, *, project_id: str, session_id: str, experiment_id: str
    ) -> ExperimentDraft | None:
        table = await self._table("sandbox_experiment_versions")
        row = await self._fetch_one(
            "sandbox_experiment_versions",
            filters={"project_id": project_id, "session_id": session_id, "experiment_id": experiment_id},
            order_by=(table.c.version.desc(),),
        )
        return self._model(ExperimentDraft, row) if row else None

    async def list_experiments(self, *, project_id: str, session_id: str) -> list[ExperimentDraft]:
        table = await self._table("sandbox_experiment_versions")
        rows = await self._fetch_all(
            "sandbox_experiment_versions",
            filters={"project_id": project_id, "session_id": session_id},
            order_by=(table.c.created_at.desc(),),
        )
        return [self._model(ExperimentDraft, row) for row in rows]

    async def save_overlay(self, overlay: GraphOverlay) -> GraphOverlay:
        values = overlay.model_dump(mode="python")
        values["base_snapshot_hash"] = overlay.base_snapshot_hash or ""
        row = await self._upsert(
            "sandbox_graph_overlays",
            values,
            conflict_columns=["overlay_id"],
            update_columns=["base_snapshot_hash", "operation_hash", "status", "updated_at"],
        )
        return self._model(GraphOverlay, row)

    async def get_overlay(
        self, *, project_id: str, session_id: str, overlay_id: str
    ) -> GraphOverlay | None:
        row = await self._fetch_one(
            "sandbox_graph_overlays",
            filters={"project_id": project_id, "session_id": session_id, "overlay_id": overlay_id},
        )
        return self._model(GraphOverlay, row) if row else None

    async def list_overlays(self, *, project_id: str, session_id: str) -> list[GraphOverlay]:
        table = await self._table("sandbox_graph_overlays")
        rows = await self._fetch_all(
            "sandbox_graph_overlays",
            filters={"project_id": project_id, "session_id": session_id},
            order_by=(table.c.updated_at.desc(),),
        )
        return [self._model(GraphOverlay, row) for row in rows]

    async def save_overlay_operation(self, operation: GraphOverlayOperation) -> GraphOverlayOperation:
        row = await self._upsert(
            "sandbox_graph_overlay_operations",
            operation.model_dump(mode="python"),
            conflict_columns=["operation_id"],
            update_columns=[],
        )
        return self._model(GraphOverlayOperation, row)

    async def list_overlay_operations(self, *, overlay_id: str) -> list[GraphOverlayOperation]:
        table = await self._table("sandbox_graph_overlay_operations")
        rows = await self._fetch_all(
            "sandbox_graph_overlay_operations",
            filters={"overlay_id": overlay_id},
            order_by=(table.c.sequence.asc(),),
        )
        return [self._model(GraphOverlayOperation, row) for row in rows]

    async def save_assessment(self, assessment: OverlayAssessment) -> OverlayAssessment:
        overlay = await self._overlay_for_id(assessment.overlay_id)
        row = await self._upsert(
            "sandbox_overlay_assessments",
            assessment.model_dump(mode="python") | {"project_id": overlay.project_id},
            conflict_columns=["assessment_id"],
            update_columns=[],
        )
        return self._model(OverlayAssessment, row)

    async def get_assessment(self, *, overlay_id: str) -> OverlayAssessment | None:
        table = await self._table("sandbox_overlay_assessments")
        row = await self._fetch_one(
            "sandbox_overlay_assessments",
            filters={"overlay_id": overlay_id},
            order_by=(table.c.created_at.desc(),),
        )
        return self._model(OverlayAssessment, row) if row else None

    async def get_assessment_by_id(self, *, assessment_id: str) -> OverlayAssessment | None:
        row = await self._fetch_one(
            "sandbox_overlay_assessments", filters={"assessment_id": assessment_id}
        )
        return self._model(OverlayAssessment, row) if row else None

    async def save_adoption_proposal(self, proposal: AdoptionProposal) -> AdoptionProposal:
        row = await self._upsert(
            "sandbox_adoption_proposals",
            proposal.model_dump(mode="python"),
            conflict_columns=["proposal_id"],
            update_columns=["status", "updated_at"],
        )
        return self._model(AdoptionProposal, row)

    async def get_adoption_proposal(
        self, *, project_id: str, session_id: str, proposal_id: str
    ) -> AdoptionProposal | None:
        row = await self._fetch_one(
            "sandbox_adoption_proposals",
            filters={"project_id": project_id, "session_id": session_id, "proposal_id": proposal_id},
        )
        return self._model(AdoptionProposal, row) if row else None

    async def find_adoption_proposal(self, *, project_id: str, proposal_id: str) -> AdoptionProposal | None:
        row = await self._fetch_one(
            "sandbox_adoption_proposals", filters={"project_id": project_id, "proposal_id": proposal_id}
        )
        return self._model(AdoptionProposal, row) if row else None

    async def list_adoption_proposals(
        self, *, project_id: str, session_id: str
    ) -> list[AdoptionProposal]:
        table = await self._table("sandbox_adoption_proposals")
        rows = await self._fetch_all(
            "sandbox_adoption_proposals",
            filters={"project_id": project_id, "session_id": session_id},
            order_by=(table.c.created_at.desc(),),
        )
        return [self._model(AdoptionProposal, row) for row in rows]

    async def save_adoption_decision(self, decision: AdoptionDecision) -> AdoptionDecision:
        proposal = await self._proposal_for_id(decision.proposal_id)
        row = await self._upsert(
            "sandbox_adoption_decisions",
            decision.model_dump(mode="python") | {"project_id": proposal.project_id},
            conflict_columns=["decision_id"],
            update_columns=[],
        )
        return self._model(AdoptionDecision, row)

    async def save_dataset(self, dataset: DatasetRecord) -> DatasetRecord:
        row = await self._upsert(
            "analysis_datasets",
            dataset.model_dump(mode="python"),
            conflict_columns=["dataset_id"],
            update_columns=["status", "retention_until", "deleted_at"],
        )
        return self._model(DatasetRecord, row)

    async def get_dataset(
        self, *, project_id: str, dataset_id: str, include_deleted: bool = False
    ) -> DatasetRecord | None:
        table = await self._table("analysis_datasets")
        statement = sa.select(table).where(*self._where(table, project_id=project_id, dataset_id=dataset_id))
        if not include_deleted:
            statement = statement.where(table.c.status != "deleted")
        async with self.engine.connect() as connection:
            row = (await connection.execute(statement.limit(1))).mappings().first()
        return self._model(DatasetRecord, row) if row else None

    async def list_datasets(self, *, project_id: str) -> list[DatasetRecord]:
        table = await self._table("analysis_datasets")
        statement = (
            sa.select(table)
            .where(table.c.project_id == project_id, table.c.status != "deleted")
            .order_by(table.c.created_at.desc())
        )
        async with self.engine.connect() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [self._model(DatasetRecord, row) for row in rows]

    async def save_dataset_profile(self, profile: DatasetProfile) -> DatasetProfile:
        table = await self._table("analysis_dataset_profiles")
        values = profile.model_dump(mode="python")
        values["columns_json"] = [column.model_dump(mode="json") for column in profile.columns]
        values.pop("columns", None)
        typed = self._typed_values(table, values)
        insert = pg_insert(table).values(**typed).on_conflict_do_nothing().returning(table)
        async with self.engine.begin() as connection:
            row = (await connection.execute(insert)).mappings().first()
            if row is None:
                row = (
                    await connection.execute(
                        sa.select(table).where(
                            table.c.dataset_id == self._coerce(table.c.dataset_id, profile.dataset_id),
                            table.c.content_hash == profile.content_hash,
                            table.c.profiler_version == profile.profiler_version,
                        )
                    )
                ).mappings().one()
        return self._model(DatasetProfile, row, {"columns": "columns_json"})

    async def list_dataset_profiles(self, *, project_id: str, dataset_id: str) -> list[DatasetProfile]:
        table = await self._table("analysis_dataset_profiles")
        rows = await self._fetch_all(
            "analysis_dataset_profiles",
            filters={"project_id": project_id, "dataset_id": dataset_id},
            order_by=(table.c.version.asc(),),
        )
        return [self._model(DatasetProfile, row, {"columns": "columns_json"}) for row in rows]

    async def get_dataset_profile(
        self, *, project_id: str, dataset_id: str, version: int
    ) -> DatasetProfile | None:
        row = await self._fetch_one(
            "analysis_dataset_profiles",
            filters={"project_id": project_id, "dataset_id": dataset_id, "version": version},
        )
        return self._model(DatasetProfile, row, {"columns": "columns_json"}) if row else None

    async def save_analysis_question(self, question: AnalysisQuestion) -> AnalysisQuestion:
        row = await self._upsert(
            "analysis_questions",
            question.model_dump(mode="python"),
            conflict_columns=["question_id"],
            update_columns=[],
        )
        return self._model(AnalysisQuestion, row)

    async def get_analysis_question(
        self, *, project_id: str, dataset_id: str, question_id: str
    ) -> AnalysisQuestion | None:
        row = await self._fetch_one(
            "analysis_questions",
            filters={"project_id": project_id, "dataset_id": dataset_id, "question_id": question_id},
        )
        return self._model(AnalysisQuestion, row) if row else None

    async def list_analysis_questions(
        self, *, project_id: str, dataset_id: str | None = None
    ) -> list[AnalysisQuestion]:
        table = await self._table("analysis_questions")
        filters: dict[str, Any] = {"project_id": project_id}
        if dataset_id is not None:
            filters["dataset_id"] = dataset_id
        rows = await self._fetch_all(
            "analysis_questions", filters=filters, order_by=(table.c.created_at.desc(),)
        )
        return [self._model(AnalysisQuestion, row) for row in rows]

    async def save_analysis_plan(self, plan: AnalysisPlanVersion) -> AnalysisPlanVersion:
        values = plan.model_dump(mode="python") | {"plan_version_id": str(uuid4())}
        row = await self._upsert(
            "analysis_plan_versions",
            values,
            conflict_columns=["plan_id", "version"],
            update_columns=["status"],
        )
        return self._model(AnalysisPlanVersion, row)

    async def get_analysis_plan(
        self, *, project_id: str, plan_id: str, version: int
    ) -> AnalysisPlanVersion | None:
        row = await self._fetch_one(
            "analysis_plan_versions",
            filters={"project_id": project_id, "plan_id": plan_id, "version": version},
        )
        return self._model(AnalysisPlanVersion, row) if row else None

    async def list_analysis_plans(
        self, *, project_id: str, dataset_id: str | None = None, plan_id: str | None = None
    ) -> list[AnalysisPlanVersion]:
        table = await self._table("analysis_plan_versions")
        filters: dict[str, Any] = {"project_id": project_id}
        if dataset_id is not None:
            filters["dataset_id"] = dataset_id
        if plan_id is not None:
            filters["plan_id"] = plan_id
        rows = await self._fetch_all(
            "analysis_plan_versions", filters=filters, order_by=(table.c.created_at.desc(),)
        )
        return [self._model(AnalysisPlanVersion, row) for row in rows]

    async def save_analysis_plan_decision(self, decision: AnalysisPlanDecision) -> AnalysisPlanDecision:
        row = await self._upsert(
            "analysis_plan_decisions",
            decision.model_dump(mode="python"),
            conflict_columns=["project_id", "idempotency_key"],
            update_columns=[],
        )
        return self._model(AnalysisPlanDecision, row)

    async def commit_analysis_plan_review(
        self, plan: AnalysisPlanVersion, decision: AnalysisPlanDecision
    ) -> tuple[AnalysisPlanVersion, AnalysisPlanDecision]:
        """Atomically append a decision and move the referenced immutable plan status."""

        plans = await self._table("analysis_plan_versions")
        decisions = await self._table("analysis_plan_decisions")
        decision_values = self._typed_values(decisions, decision.model_dump(mode="python"))
        async with self.engine.begin() as connection:
            inserted = (
                await connection.execute(
                    pg_insert(decisions).values(**decision_values).on_conflict_do_nothing(
                        index_elements=[decisions.c.project_id, decisions.c.idempotency_key]
                    ).returning(decisions)
                )
            ).mappings().first()
            if inserted is None:
                inserted = (
                    await connection.execute(
                        sa.select(decisions).where(
                            decisions.c.project_id == decision.project_id,
                            decisions.c.idempotency_key == decision.idempotency_key,
                        )
                    )
                ).mappings().one()
                plan_row = (
                    await connection.execute(
                        sa.select(plans).where(
                            plans.c.project_id == inserted["project_id"],
                            plans.c.plan_id == inserted["plan_id"],
                            plans.c.version == inserted["plan_version"],
                        )
                    )
                ).mappings().one()
                return self._model(AnalysisPlanVersion, plan_row), self._model(AnalysisPlanDecision, inserted)
            plan_row = (
                await connection.execute(
                    sa.update(plans)
                    .where(
                        plans.c.project_id == plan.project_id,
                        plans.c.plan_id == self._coerce(plans.c.plan_id, plan.plan_id),
                        plans.c.version == plan.version,
                    )
                    .values(status=plan.status.value)
                    .returning(plans)
                )
            ).mappings().one()
        return self._model(AnalysisPlanVersion, plan_row), self._model(AnalysisPlanDecision, inserted)

    async def get_analysis_plan_decision_by_idempotency(
        self, *, project_id: str, idempotency_key: str
    ) -> AnalysisPlanDecision | None:
        row = await self._fetch_one(
            "analysis_plan_decisions", filters={"project_id": project_id, "idempotency_key": idempotency_key}
        )
        return self._model(AnalysisPlanDecision, row) if row else None

    async def list_analysis_plan_decisions(
        self, *, project_id: str, plan_id: str, version: int
    ) -> list[AnalysisPlanDecision]:
        table = await self._table("analysis_plan_decisions")
        rows = await self._fetch_all(
            "analysis_plan_decisions",
            filters={"project_id": project_id, "plan_id": plan_id, "plan_version": version},
            order_by=(table.c.created_at.asc(),),
        )
        return [self._model(AnalysisPlanDecision, row) for row in rows]

    async def save_analysis_code(self, code: AnalysisCodeVersion) -> AnalysisCodeVersion:
        values = code.model_dump(mode="python") | {
            "storage_key": f"database://analysis-code/{code.code_version_id}"
        }
        row = await self._upsert(
            "analysis_code_versions",
            values,
            conflict_columns=["code_version_id"],
            update_columns=[],
        )
        return self._model(AnalysisCodeVersion, row)

    async def get_analysis_code(
        self, *, project_id: str, code_version_id: str
    ) -> AnalysisCodeVersion | None:
        row = await self._fetch_one(
            "analysis_code_versions", filters={"project_id": project_id, "code_version_id": code_version_id}
        )
        return self._model(AnalysisCodeVersion, row) if row and row.get("source_code") else None

    async def list_analysis_codes_for_plan(
        self, *, project_id: str, plan_id: str, plan_version: int
    ) -> list[AnalysisCodeVersion]:
        table = await self._table("analysis_code_versions")
        rows = await self._fetch_all(
            "analysis_code_versions",
            filters={"project_id": project_id, "plan_id": plan_id, "plan_version": plan_version},
            order_by=(table.c.version.asc(),),
        )
        return [self._model(AnalysisCodeVersion, row) for row in rows if row.get("source_code")]

    async def create_sandbox_run(self, run: SandboxRun) -> SandboxRun:
        runs = await self._table("sandbox_runs")
        history = await self._table("sandbox_run_status_history")
        manifest_json = run.manifest.model_dump(mode="json")
        values = run.model_dump(mode="python", exclude={"manifest"}) | {
            "manifest_json": manifest_json,
            "manifest_hash": self._hash(manifest_json),
        }
        typed = self._typed_values(runs, values)
        insert = (
            pg_insert(runs)
            .values(**typed)
            .on_conflict_do_nothing(index_elements=[runs.c.project_id, runs.c.idempotency_key])
            .returning(runs)
        )
        async with self.engine.begin() as connection:
            row = (await connection.execute(insert)).mappings().first()
            if row is None:
                row = (
                    await connection.execute(
                        sa.select(runs).where(
                            runs.c.project_id == run.project_id,
                            runs.c.idempotency_key == run.idempotency_key,
                        )
                    )
                ).mappings().one()
            else:
                records = [
                    {
                        "history_id": str(uuid4()),
                        "run_id": run.run_id,
                        "project_id": run.project_id,
                        "from_status": None,
                        "to_status": SandboxRunStatus.PENDING_APPROVAL.value,
                        "changed_by": "control-plane",
                        "reason": "execution_confirmed",
                        "created_at": run.created_at,
                    },
                    {
                        "history_id": str(uuid4()),
                        "run_id": run.run_id,
                        "project_id": run.project_id,
                        "from_status": SandboxRunStatus.PENDING_APPROVAL.value,
                        "to_status": run.status.value,
                        "changed_by": "control-plane",
                        "reason": "run_queued",
                        "created_at": run.created_at,
                    },
                ]
                await connection.execute(sa.insert(history), [self._typed_values(history, item) for item in records])
        return self._run_from_row(row)

    async def get_sandbox_run(self, *, project_id: str, run_id: str) -> SandboxRun | None:
        row = await self._fetch_one("sandbox_runs", filters={"project_id": project_id, "run_id": run_id})
        return self._run_from_row(row) if row else None

    async def list_sandbox_runs(
        self, *, project_id: str, plan_id: str, plan_version: int
    ) -> list[SandboxRun]:
        table = await self._table("sandbox_runs")
        rows = await self._fetch_all(
            "sandbox_runs",
            filters={
                "project_id": project_id,
                "plan_id": plan_id,
                "plan_version": plan_version,
            },
            order_by=(table.c.created_at.asc(),),
        )
        return [self._run_from_row(row) for row in rows]

    async def get_sandbox_run_by_idempotency(
        self, *, project_id: str, idempotency_key: str
    ) -> SandboxRun | None:
        row = await self._fetch_one(
            "sandbox_runs", filters={"project_id": project_id, "idempotency_key": idempotency_key}
        )
        return self._run_from_row(row) if row else None

    async def update_sandbox_run(
        self, run: SandboxRun, *, changed_by: str, reason: str | None = None
    ) -> SandboxRun:
        runs = await self._table("sandbox_runs")
        history = await self._table("sandbox_run_status_history")
        async with self.engine.begin() as connection:
            previous = (
                await connection.execute(
                    sa.select(runs)
                    .where(runs.c.run_id == self._coerce(runs.c.run_id, run.run_id))
                    .with_for_update()
                )
            ).mappings().first()
            if previous is None:
                raise KeyError(run.run_id)
            values = self._typed_values(
                runs,
                run.model_dump(mode="python", include={"status", "lease_owner", "lease_expires_at", "error_code", "updated_at"}),
            )
            row = (
                await connection.execute(
                    sa.update(runs)
                    .where(runs.c.run_id == self._coerce(runs.c.run_id, run.run_id))
                    .values(**values)
                    .returning(runs)
                )
            ).mappings().one()
            if previous["status"] != run.status.value:
                await connection.execute(
                    sa.insert(history).values(
                        **self._typed_values(
                            history,
                            {
                                "history_id": str(uuid4()),
                                "run_id": run.run_id,
                                "project_id": run.project_id,
                                "from_status": previous["status"],
                                "to_status": run.status.value,
                                "changed_by": changed_by,
                                "reason": reason,
                                "created_at": run.updated_at,
                            },
                        )
                    )
                )
        return self._run_from_row(row)

    async def claim_sandbox_run(self, *, worker_id: str, now, lease_seconds: int) -> SandboxRun | None:
        runs = await self._table("sandbox_runs")
        history = await self._table("sandbox_run_status_history")
        eligible = sa.or_(
            runs.c.status == SandboxRunStatus.QUEUED.value,
            sa.and_(runs.c.status == SandboxRunStatus.RUNNING.value, runs.c.lease_expires_at <= now),
        )
        async with self.engine.begin() as connection:
            previous = (
                await connection.execute(
                    sa.select(runs)
                    .where(eligible)
                    .order_by(runs.c.created_at.asc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).mappings().first()
            if previous is None:
                return None
            reclaimed = previous["status"] == SandboxRunStatus.RUNNING.value
            row = (
                await connection.execute(
                    sa.update(runs)
                    .where(runs.c.run_id == previous["run_id"])
                    .values(
                        status=SandboxRunStatus.RUNNING.value,
                        lease_owner=worker_id,
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                        updated_at=now,
                    )
                    .returning(runs)
                )
            ).mappings().one()
            if not reclaimed:
                await connection.execute(
                    sa.insert(history).values(
                        **self._typed_values(
                            history,
                            {
                                "history_id": str(uuid4()),
                                "run_id": str(previous["run_id"]),
                                "project_id": previous["project_id"],
                                "from_status": previous["status"],
                                "to_status": SandboxRunStatus.RUNNING.value,
                                "changed_by": worker_id,
                                "reason": "lease_claimed",
                                "created_at": now,
                            },
                        )
                    )
                )
        return self._run_from_row(row)

    async def renew_sandbox_run_lease(
        self, *, run_id: str, worker_id: str, now, lease_seconds: int
    ) -> bool:
        """Atomically extend a lease only while this worker still owns the run."""
        if lease_seconds <= 0:
            return False
        runs = await self._table("sandbox_runs")
        async with self.engine.begin() as connection:
            renewed = (
                await connection.execute(
                    sa.update(runs)
                    .where(
                        runs.c.run_id == self._coerce(runs.c.run_id, run_id),
                        runs.c.status == SandboxRunStatus.RUNNING.value,
                        runs.c.lease_owner == worker_id,
                    )
                    .values(
                        lease_expires_at=now + timedelta(seconds=lease_seconds),
                        updated_at=now,
                    )
                    .returning(runs.c.run_id)
                )
            ).scalar_one_or_none()
        return renewed is not None

    async def consume_manifest_nonce(self, *, nonce: str, run_id: str) -> bool:
        table = await self._table("sandbox_manifest_nonces")
        values = self._typed_values(table, {"nonce": nonce, "run_id": run_id})
        async with self.engine.begin() as connection:
            inserted = (
                await connection.execute(
                    pg_insert(table).values(**values).on_conflict_do_nothing(
                        index_elements=[table.c.nonce]
                    ).returning(table.c.run_id)
                )
            ).scalar_one_or_none()
            if inserted is not None:
                return True
            owner = (
                await connection.execute(sa.select(table.c.run_id).where(table.c.nonce == nonce))
            ).scalar_one()
            return str(owner) == run_id

    async def list_run_status_history(
        self, *, project_id: str, run_id: str
    ) -> list[SandboxRunStatusHistory]:
        table = await self._table("sandbox_run_status_history")
        rows = await self._fetch_all(
            "sandbox_run_status_history",
            filters={"project_id": project_id, "run_id": run_id},
            order_by=(table.c.created_at.asc(),),
        )
        return [self._model(SandboxRunStatusHistory, row) for row in rows]

    async def list_sandbox_run_status_history(
        self, *, project_id: str, run_id: str
    ) -> list[SandboxRunStatusHistory]:
        return await self.list_run_status_history(project_id=project_id, run_id=run_id)

    async def save_artifact(self, artifact: AnalysisArtifact) -> AnalysisArtifact:
        row = await self._upsert(
            "analysis_artifacts",
            artifact.model_dump(mode="python"),
            conflict_columns=["run_id", "filename"],
            update_columns=[],
        )
        return self._model(AnalysisArtifact, row)

    async def list_artifacts(self, *, project_id: str, run_id: str) -> list[AnalysisArtifact]:
        table = await self._table("analysis_artifacts")
        rows = await self._fetch_all(
            "analysis_artifacts",
            filters={"project_id": project_id, "run_id": run_id},
            order_by=(table.c.created_at.asc(),),
        )
        return [self._model(AnalysisArtifact, row) for row in rows]

    async def save_result_validation(self, validation: AnalysisResultValidation) -> AnalysisResultValidation:
        table = await self._table("analysis_result_validations")
        values = validation.model_dump(mode="python")
        values["errors_json"] = values.pop("errors")
        values["warnings_json"] = values.pop("warnings")
        typed = self._typed_values(table, values)
        async with self.engine.begin() as connection:
            row = (
                await connection.execute(
                    pg_insert(table).values(**typed).on_conflict_do_nothing(
                        index_elements=[table.c.run_id]
                    ).returning(table)
                )
            ).mappings().first()
            if row is None:
                row = (
                    await connection.execute(
                        sa.select(table).where(table.c.run_id == self._coerce(table.c.run_id, validation.run_id))
                    )
                ).mappings().one()
        return self._model(AnalysisResultValidation, row, {"errors": "errors_json", "warnings": "warnings_json"})

    async def get_result_validation(
        self, *, project_id: str, run_id: str
    ) -> AnalysisResultValidation | None:
        row = await self._fetch_one(
            "analysis_result_validations", filters={"project_id": project_id, "run_id": run_id}
        )
        return (
            self._model(AnalysisResultValidation, row, {"errors": "errors_json", "warnings": "warnings_json"})
            if row
            else None
        )

    async def save_result_interpretation(
        self, record: AnalysisResultInterpretationRecord
    ) -> AnalysisResultInterpretationRecord:
        table = await self._table("analysis_result_interpretations")
        values = record.model_dump(mode="python")
        values["narrative_json"] = values.pop("narrative")
        values["numeric_claims_json"] = [claim.model_dump(mode="json") for claim in record.numeric_claims]
        values.pop("numeric_claims", None)
        values["limitations_json"] = values.pop("limitations")
        values["citation_ids_json"] = values.pop("citation_ids")
        typed = self._typed_values(table, values)
        async with self.engine.begin() as connection:
            row = (
                await connection.execute(
                    pg_insert(table).values(**typed).on_conflict_do_nothing(
                        index_elements=[table.c.project_id, table.c.run_id]
                    ).returning(table)
                )
            ).mappings().first()
            if row is None:
                row = (
                    await connection.execute(
                        sa.select(table).where(
                            table.c.project_id == record.project_id,
                            table.c.run_id == self._coerce(table.c.run_id, record.run_id),
                        )
                    )
                ).mappings().one()
        return self._model(
            AnalysisResultInterpretationRecord,
            row,
            {
                "narrative": "narrative_json",
                "numeric_claims": "numeric_claims_json",
                "limitations": "limitations_json",
                "citation_ids": "citation_ids_json",
            },
        )

    async def get_result_interpretation(
        self, *, project_id: str, run_id: str
    ) -> AnalysisResultInterpretationRecord | None:
        row = await self._fetch_one(
            "analysis_result_interpretations", filters={"project_id": project_id, "run_id": run_id}
        )
        return (
            self._model(
                AnalysisResultInterpretationRecord,
                row,
                {
                    "narrative": "narrative_json",
                    "numeric_claims": "numeric_claims_json",
                    "limitations": "limitations_json",
                    "citation_ids": "citation_ids_json",
                },
            )
            if row
            else None
        )
    async def save_analysis_citation(self, citation: AnalysisCitation) -> AnalysisCitation:
        table = await self._table("analysis_citations")
        typed = self._typed_values(table, citation.model_dump(mode="python"))
        async with self.engine.begin() as connection:
            row = (
                await connection.execute(
                    pg_insert(table).values(**typed).on_conflict_do_nothing(
                        index_elements=[table.c.run_id, table.c.artifact_id, table.c.locator, table.c.value_hash]
                    ).returning(table)
                )
            ).mappings().first()
            if row is None:
                row = (
                    await connection.execute(
                        sa.select(table).where(
                            table.c.run_id == self._coerce(table.c.run_id, citation.run_id),
                            table.c.artifact_id == self._coerce(table.c.artifact_id, citation.artifact_id),
                            table.c.locator == citation.locator,
                            table.c.value_hash == citation.value_hash,
                        )
                    )
                ).mappings().one()
        return self._model(AnalysisCitation, row)

    async def list_analysis_citations(self, *, project_id: str, run_id: str) -> list[AnalysisCitation]:
        table = await self._table("analysis_citations")
        rows = await self._fetch_all(
            "analysis_citations",
            filters={"project_id": project_id, "run_id": run_id},
            order_by=(table.c.created_at.asc(),),
        )
        return [self._model(AnalysisCitation, row) for row in rows]

    async def save_analysis_result_review(self, review: AnalysisResultReview) -> AnalysisResultReview:
        row = await self._upsert(
            "analysis_result_reviews",
            review.model_dump(mode="python"),
            conflict_columns=["project_id", "idempotency_key"],
            update_columns=[],
        )
        return self._model(AnalysisResultReview, row)

    async def commit_result_review(
        self,
        run: SandboxRun,
        review: AnalysisResultReview,
        *,
        changed_by: str,
        reason: str | None = None,
    ) -> tuple[SandboxRun, AnalysisResultReview]:
        """Atomically append result review, terminal run state, and status history."""

        runs = await self._table("sandbox_runs")
        reviews = await self._table("analysis_result_reviews")
        history = await self._table("sandbox_run_status_history")
        review_values = self._typed_values(reviews, review.model_dump(mode="python"))
        async with self.engine.begin() as connection:
            inserted = (
                await connection.execute(
                    pg_insert(reviews).values(**review_values).on_conflict_do_nothing(
                        index_elements=[reviews.c.project_id, reviews.c.idempotency_key]
                    ).returning(reviews)
                )
            ).mappings().first()
            if inserted is None:
                inserted = (
                    await connection.execute(
                        sa.select(reviews).where(
                            reviews.c.project_id == review.project_id,
                            reviews.c.idempotency_key == review.idempotency_key,
                        )
                    )
                ).mappings().one()
                run_row = (
                    await connection.execute(
                        sa.select(runs).where(runs.c.run_id == inserted["run_id"])
                    )
                ).mappings().one()
                return self._run_from_row(run_row), self._model(AnalysisResultReview, inserted)
            previous = (
                await connection.execute(
                    sa.select(runs)
                    .where(
                        runs.c.project_id == run.project_id,
                        runs.c.run_id == self._coerce(runs.c.run_id, run.run_id),
                    )
                    .with_for_update()
                )
            ).mappings().one()
            run_row = (
                await connection.execute(
                    sa.update(runs)
                    .where(runs.c.run_id == previous["run_id"])
                    .values(
                        status=run.status.value,
                        lease_owner=run.lease_owner,
                        lease_expires_at=run.lease_expires_at,
                        error_code=run.error_code,
                        updated_at=run.updated_at,
                    )
                    .returning(runs)
                )
            ).mappings().one()
            if previous["status"] != run.status.value:
                await connection.execute(
                    sa.insert(history).values(
                        **self._typed_values(
                            history,
                            {
                                "history_id": str(uuid4()),
                                "run_id": run.run_id,
                                "project_id": run.project_id,
                                "from_status": previous["status"],
                                "to_status": run.status.value,
                                "changed_by": changed_by,
                                "reason": reason,
                                "created_at": run.updated_at,
                            },
                        )
                    )
                )
        return self._run_from_row(run_row), self._model(AnalysisResultReview, inserted)

    async def get_analysis_result_review_by_idempotency(
        self, *, project_id: str, idempotency_key: str
    ) -> AnalysisResultReview | None:
        row = await self._fetch_one(
            "analysis_result_reviews", filters={"project_id": project_id, "idempotency_key": idempotency_key}
        )
        return self._model(AnalysisResultReview, row) if row else None

    async def save_reproducibility_bundle(
        self, bundle: AnalysisReproducibilityBundle
    ) -> AnalysisReproducibilityBundle:
        table = await self._table("analysis_reproducibility_bundles")
        values = bundle.model_dump(mode="python")
        values["artifact_hashes_json"] = values.pop("artifact_hashes")
        typed = self._typed_values(table, values)
        async with self.engine.begin() as connection:
            row = (
                await connection.execute(
                    pg_insert(table).values(**typed).on_conflict_do_nothing(
                        index_elements=[table.c.run_id]
                    ).returning(table)
                )
            ).mappings().first()
            if row is None:
                row = (
                    await connection.execute(
                        sa.select(table).where(table.c.run_id == self._coerce(table.c.run_id, bundle.run_id))
                    )
                ).mappings().one()
        return self._model(AnalysisReproducibilityBundle, row, {"artifact_hashes": "artifact_hashes_json"})

    async def get_reproducibility_bundle(
        self, *, project_id: str, run_id: str
    ) -> AnalysisReproducibilityBundle | None:
        row = await self._fetch_one(
            "analysis_reproducibility_bundles", filters={"project_id": project_id, "run_id": run_id}
        )
        return (
            self._model(AnalysisReproducibilityBundle, row, {"artifact_hashes": "artifact_hashes_json"})
            if row
            else None
        )

    async def _session_for_id(self, session_id: str) -> SandboxSessionResponse:
        row = await self._fetch_one("research_sandbox_sessions", filters={"session_id": session_id})
        if row is None:
            raise KeyError(session_id)
        return self._model(SandboxSessionResponse, row)

    async def _overlay_for_id(self, overlay_id: str) -> GraphOverlay:
        row = await self._fetch_one("sandbox_graph_overlays", filters={"overlay_id": overlay_id})
        if row is None:
            raise KeyError(overlay_id)
        return self._model(GraphOverlay, row)

    async def _proposal_for_id(self, proposal_id: str) -> AdoptionProposal:
        row = await self._fetch_one("sandbox_adoption_proposals", filters={"proposal_id": proposal_id})
        if row is None:
            raise KeyError(proposal_id)
        return self._model(AdoptionProposal, row)

    @classmethod
    def _run_from_row(cls, row: sa.RowMapping) -> SandboxRun:
        clean = cls._clean_row(row) or {}
        clean["manifest"] = SandboxExecutionManifest.model_validate(clean.pop("manifest_json"))
        return SandboxRun.model_validate(
            {key: value for key, value in clean.items() if key in SandboxRun.model_fields}
        )
