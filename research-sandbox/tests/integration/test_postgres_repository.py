"""Opt-in integration test against a real PostgreSQL sandbox database.

Set ``SANDBOX_TEST_POSTGRES_URL`` to an isolated database.  The default test
suite skips this test rather than silently substituting SQLite, whose locking,
UUID and ``SKIP LOCKED`` behavior cannot validate the durable worker contract.
"""

from datetime import datetime, timedelta, timezone
import asyncio
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config

from sandbox_service.domain.analysis_plans import (
    AnalysisObjective,
    AnalysisPlanDecision,
    AnalysisPlanStatus,
    AnalysisPlanVersion,
)
from sandbox_service.domain.datasets import (
    AnalysisQuestion,
    DatasetClassification,
    DatasetProfile,
    DatasetRecord,
    DatasetStatus,
)
from sandbox_service.domain.execution import (
    AnalysisCodeStatus,
    AnalysisCodeVersion,
    SandboxExecutionManifest,
    SandboxRun,
    SandboxRunStatus,
)
from sandbox_service.domain.sessions import (
    SandboxEntrypoint,
    SandboxMode,
    SandboxSessionResponse,
    SandboxSessionStatus,
)
from sandbox_service.repositories.postgres import PostgresSandboxRepository


DATABASE_URL = os.getenv("SANDBOX_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="SANDBOX_TEST_POSTGRES_URL is not configured for the opt-in PostgreSQL test",
)


@pytest.fixture(scope="session")
def event_loop_policy():
    """Psycopg async requires a selector loop on Windows test hosts."""

    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.mark.asyncio
async def test_postgres_migration_reload_idempotency_and_lease(monkeypatch) -> None:
    assert DATABASE_URL is not None
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("SANDBOX_DATABASE_URL", DATABASE_URL)
    alembic = Config(str(root / "alembic.ini"))
    command.upgrade(alembic, "head")

    repository = PostgresSandboxRepository(DATABASE_URL)
    now = datetime.now(timezone.utc)
    project_id = f"postgres-integration-{uuid4()}"
    session = SandboxSessionResponse(
        session_id=str(uuid4()),
        project_id=project_id,
        mode=SandboxMode.DATA_ANALYSIS,
        entrypoint=SandboxEntrypoint.MANUAL,
        source_resource_id=None,
        title="PostgreSQL durability",
        initial_question=None,
        status=SandboxSessionStatus.DRAFT,
        creator_id="integration-test",
        created_at=now,
        updated_at=now,
    )
    await repository.create_session(session)

    dataset = DatasetRecord(
        dataset_id=str(uuid4()),
        project_id=project_id,
        owner_id="integration-test",
        filename="fixture.csv",
        media_type="text/csv",
        size_bytes=8,
        content_hash="1" * 64,
        storage_key=f"datasets/{project_id}/fixture.csv",
        classification=DatasetClassification.NON_SENSITIVE,
        status=DatasetStatus.VALIDATED,
        created_at=now,
    )
    await repository.save_dataset(dataset)
    profile = DatasetProfile(
        dataset_id=dataset.dataset_id,
        project_id=project_id,
        version=1,
        content_hash=dataset.content_hash,
        row_count=1,
        column_count=1,
        columns=[],
        profile_hash="2" * 64,
        created_at=now,
    )
    await repository.save_dataset_profile(profile)
    question = AnalysisQuestion(
        project_id=project_id,
        dataset_id=dataset.dataset_id,
        profile_version=1,
        objective="describe",
        research_question="Describe the fixture",
        created_at=now,
    )
    await repository.save_analysis_question(question)
    plan = AnalysisPlanVersion(
        project_id=project_id,
        dataset_id=dataset.dataset_id,
        question_id=question.question_id,
        question_version=1,
        profile_version=1,
        status=AnalysisPlanStatus.APPROVED,
        objective=AnalysisObjective.DESCRIBE,
        research_question=question.research_question,
        outcome_columns=[],
        predictor_columns=[],
        group_columns=[],
        covariate_columns=[],
        method="descriptive statistics",
        method_rationale="approved fixture plan",
        preprocessing_steps=[],
        assumption_checks=["row count"],
        evaluation_metrics=["mean"],
        limitations=[],
        plan_hash="3" * 64,
        created_at=now,
    )
    await repository.save_analysis_plan(plan)
    decision = AnalysisPlanDecision(
        project_id=project_id,
        plan_id=plan.plan_id,
        plan_version=1,
        reviewer_id="reviewer",
        decision=AnalysisPlanStatus.APPROVED,
        idempotency_key=f"approve-{uuid4()}",
        created_at=now,
    )
    await repository.save_analysis_plan_decision(decision)
    code = AnalysisCodeVersion(
        project_id=project_id,
        plan_id=plan.plan_id,
        plan_version=1,
        source_code="from sandbox_sdk import emit_result\nemit_result({'ok': True})\n",
        code_hash="4" * 64,
        prompt_version="analysis.code_generation.v1",
        status=AnalysisCodeStatus.APPROVED,
        created_at=now,
    )
    await repository.save_analysis_code(code)
    idempotency_key = f"run-{uuid4()}"
    manifest = SandboxExecutionManifest(
        operation_id=str(uuid4()),
        run_id=str(uuid4()),
        project_id=project_id,
        dataset_id=dataset.dataset_id,
        dataset_content_hash=dataset.content_hash,
        plan_id=plan.plan_id,
        plan_version=1,
        plan_hash=plan.plan_hash,
        plan_decision_id=decision.decision_id,
        code_version_id=code.code_version_id,
        code_hash=code.code_hash,
        image_digest="sandbox-runtime@sha256:" + "5" * 64,
        package_manifest_hash="6" * 64,
        random_seed=42,
        resource_limits={"timeout_seconds": 120},
        issued_at=now,
        expires_at=now + timedelta(minutes=15),
        nonce=f"nonce-{uuid4()}",
        signature="signed-for-persistence-test",
    )
    run = SandboxRun(
        run_id=manifest.run_id,
        operation_id=manifest.operation_id,
        project_id=project_id,
        dataset_id=dataset.dataset_id,
        plan_id=plan.plan_id,
        plan_version=1,
        plan_decision_id=decision.decision_id,
        code_version_id=code.code_version_id,
        idempotency_key=idempotency_key,
        status=SandboxRunStatus.QUEUED,
        manifest=manifest,
        created_at=now,
        updated_at=now,
    )
    first = await repository.create_sandbox_run(run)
    duplicate = await repository.create_sandbox_run(
        run.model_copy(
            update={
                "run_id": str(uuid4()),
                "operation_id": str(uuid4()),
            }
        )
    )
    assert duplicate.run_id == first.run_id
    claimed = await repository.claim_sandbox_run(
        worker_id="postgres-worker", now=now, lease_seconds=180
    )
    assert claimed is not None and claimed.run_id == first.run_id
    assert await repository.renew_sandbox_run_lease(
        run_id=claimed.run_id,
        worker_id="postgres-worker",
        now=now + timedelta(seconds=30),
        lease_seconds=180,
    )
    await repository.dispose()

    reloaded = PostgresSandboxRepository(DATABASE_URL)
    assert (await reloaded.get_session(project_id=project_id, session_id=session.session_id)) == session
    assert (await reloaded.get_dataset(project_id=project_id, dataset_id=dataset.dataset_id)) == dataset
    persisted_run = await reloaded.get_sandbox_run(project_id=project_id, run_id=first.run_id)
    assert persisted_run is not None and persisted_run.lease_owner == "postgres-worker"
    await reloaded.dispose()
