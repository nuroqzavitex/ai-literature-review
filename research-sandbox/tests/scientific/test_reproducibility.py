import pytest

from sandbox_service.domain.execution import SandboxRunStatus
from sandbox_service.domain.results import ResultReviewDecision, ReviewAnalysisResultRequest
from tests.unit.test_result_validation import completed_run_with_result, valid_association_result


@pytest.mark.asyncio
async def test_numeric_claims_are_cited_and_bundle_is_sealed(tmp_path) -> None:
    service, repository, run, ai = await completed_run_with_result(
        tmp_path,
        valid_association_result(),
        interpretation_responses=[
            {
                "narrative": ["The reported fit is supported by the validated result."],
                "numeric_claims": [
                    {
                        "statement": "The R-squared was 0.8.",
                        "value": 0.8,
                        "locator": "/metrics/0/value",
                    }
                ],
                "limitations": ["Association only"],
            }
        ],
    )

    validation = await service.validate_run(project_id="project-a", run_id=run.run_id)
    interpretation, citations = await service.interpret_validated(project_id="project-a", run_id=run.run_id)
    bundle = await service.get_bundle(project_id="project-a", run_id=run.run_id)

    assert validation.result_hash and validation.status.value == "validated"
    assert len(interpretation.numeric_claims) == len(citations) == 1
    assert citations[0].dataset_hash == run.manifest.dataset_content_hash
    assert citations[0].locator == "/metrics/0/value"
    assert bundle.dataset_hash == run.manifest.dataset_content_hash
    assert bundle.plan_hash == run.manifest.plan_hash
    assert bundle.code_hash == run.manifest.code_hash
    assert bundle.result_hash == validation.result_hash
    assert bundle.artifact_hashes
    assert (await service.validate_run(project_id="project-a", run_id=run.run_id)).validation_id == validation.validation_id
    assert len(ai.calls) == 1 and ai.calls[0]["prompt_version"] == "analysis.result_interpretation.v1"


@pytest.mark.asyncio
async def test_invalid_numeric_locator_is_revised_once_before_interpretation_is_saved(
    tmp_path,
) -> None:
    service, repository, run, ai = await completed_run_with_result(
        tmp_path,
        valid_association_result(),
        interpretation_responses=[
            {
                "narrative": ["The validated result supports the reported association."],
                "numeric_claims": [
                    {
                        "statement": "The reported metric was",
                        "value": 0.8,
                        "locator": "/metrics/0/name",
                    }
                ],
                "limitations": ["Association only"],
            },
            {
                "narrative": ["The validated result supports the reported association."],
                "numeric_claims": [
                    {
                        "statement": "The reported metric was",
                        "value": 0.8,
                        "locator": "/metrics/0/value",
                    }
                ],
                "limitations": ["Association only"],
            },
        ],
    )
    await service.validate_run(project_id="project-a", run_id=run.run_id)

    interpretation, citations = await service.interpret_validated(
        project_id="project-a", run_id=run.run_id
    )

    assert interpretation.numeric_claims[0].locator == "/metrics/0/value"
    assert [citation.locator for citation in citations] == ["/metrics/0/value"]
    assert len(repository.analysis_citations) == 1
    assert len(ai.calls) == 2
    assert ai.calls[1]["input_payload"]["revision"]["validation_error"] == (
        "Numeric claim locator does not resolve to a number"
    )


@pytest.mark.asyncio
async def test_result_review_is_append_only_idempotent_and_project_scoped(tmp_path) -> None:
    service, repository, run, _ = await completed_run_with_result(tmp_path, valid_association_result())
    await service.validate_run(project_id="project-a", run_id=run.run_id)

    updated, first = await service.review_result(
        project_id="project-a",
        run_id=run.run_id,
        reviewer_id="reviewer-a",
        idempotency_key="result-review-1",
        request=ReviewAnalysisResultRequest(decision=ResultReviewDecision.APPROVED),
    )
    same_run, duplicate = await service.review_result(
        project_id="project-a",
        run_id=run.run_id,
        reviewer_id="reviewer-a",
        idempotency_key="result-review-1",
        request=ReviewAnalysisResultRequest(decision=ResultReviewDecision.APPROVED),
    )

    assert updated.status is SandboxRunStatus.APPROVED
    assert same_run.status is SandboxRunStatus.APPROVED
    assert duplicate.review_id == first.review_id
    assert len(repository.analysis_result_reviews) == 1
    with pytest.raises(Exception):
        await service.get_bundle(project_id="project-b", run_id=run.run_id)
