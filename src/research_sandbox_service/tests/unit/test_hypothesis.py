import pytest

from sandbox_service.domain.hypotheses import EvidenceStatus
from sandbox_service.domain.sessions import CreateSandboxSessionRequest
from sandbox_service.hypothesis_graph import HypothesisSandboxGraph
from sandbox_service.repositories.memory import InMemorySandboxSessionRepository
from sandbox_service.session_service import SandboxSessionService
from tests.fakes import FakeProjectAIClient


@pytest.mark.asyncio
async def test_hypothesis_and_experiment_drafts_work_without_a_dataset() -> None:
    repository = InMemorySandboxSessionRepository()
    session_service = SandboxSessionService(repository=repository)
    session = await session_service.create_session(
        project_id="project-a",
        actor_id="researcher-a",
        request=CreateSandboxSessionRequest(
            mode="hypothesis",
            entrypoint="manual",
            title="No-dataset hypothesis",
            initial_question="Does treatment X improve Y?",
        ),
    )
    ai = FakeProjectAIClient(
        responses=[
            {
                "statement": "Treatment X is associated with improved Y.",
                "rationale": "This is a testable, preliminary proposition.",
                "supporting_evidence_refs": [],
                "counterevidence_refs": [],
                "assumptions": ["Y can be measured"],
                "falsification_criteria": ["No improvement in a controlled comparison"],
                "required_data": ["Treatment assignment", "Y outcome"],
                "limitations": ["No pinned evidence context"],
            },
            {
                "objective": "Compare Y between treatment groups.",
                "independent_variables": ["treatment"],
                "dependent_variables": ["Y"],
                "controls": ["baseline Y"],
                "data_requirements": ["A future non-sensitive dataset"],
                "method_candidates": ["controlled comparison"],
                "evaluation_metrics": ["effect size"],
                "assumption_checks": ["group comparability"],
                "stopping_criteria": ["predefined sample size"],
                "risks": ["confounding"],
            },
        ]
    )
    graph = HypothesisSandboxGraph(repository=repository, ai_client=ai)

    hypothesis = await graph.generate_hypothesis(
        project_id="project-a", session_id=session.session_id, actor_id="researcher-a",
        output_language="vi",
    )
    experiment = await graph.generate_experiment(
        project_id="project-a",
        session_id=session.session_id,
        hypothesis_id=hypothesis.hypothesis_id,
        actor_id="researcher-a",
        output_language="vi",
    )

    assert hypothesis.version == 1
    assert hypothesis.evidence_status is EvidenceStatus.UNVERIFIED
    assert "không được trình bày nội dung này như một sự thật" in hypothesis.limitations[-1]
    assert experiment.hypothesis_id == hypothesis.hypothesis_id
    assert experiment.version == 1
    assert len(await graph.list_hypotheses(project_id="project-a", session_id=session.session_id)) == 1
    assert len(await graph.list_experiments(project_id="project-a", session_id=session.session_id)) == 1
    assert [call["prompt_version"] for call in ai.calls] == [
        "sandbox.hypothesis_generation.v1",
        "sandbox.experiment_design.v1",
    ]
    assert all(call["input_payload"]["output_language"] == "vi" for call in ai.calls)
