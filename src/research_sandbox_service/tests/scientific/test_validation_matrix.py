"""Scientific release-gate fixtures for deterministic result validation."""

import json

import pytest

from sandbox_service.domain.analysis_plans import AnalysisPlanVersion
from sandbox_service.domain.datasets import DatasetColumnProfile, DatasetProfile
from sandbox_service.execution.result_validator import ResultValidationError, ResultValidator


def _profile(*, rows: int = 10) -> DatasetProfile:
    columns = [
        DatasetColumnProfile(
            name=name,
            dtype="int64",
            missing_count=0,
            missing_ratio=0,
            unique_count=rows,
            distribution={"kind": "numeric", "count": rows, "min": 0, "max": rows - 1},
        )
        for name in ("outcome", "predictor")
    ]
    return DatasetProfile(
        dataset_id="dataset-a",
        project_id="project-a",
        version=1,
        content_hash="a" * 64,
        row_count=rows,
        column_count=2,
        columns=columns,
        profile_hash="b" * 64,
    )


def _plan(*, objective: str = "predict") -> AnalysisPlanVersion:
    return AnalysisPlanVersion(
        project_id="project-a",
        dataset_id="dataset-a",
        question_id="question-a",
        question_version=1,
        profile_version=1,
        objective=objective,
        research_question="Can predictor estimate outcome?",
        outcome_columns=["outcome"],
        predictor_columns=["predictor"],
        group_columns=[],
        covariate_columns=[],
        method="Random forest" if objective == "predict" else "Linear regression",
        method_rationale="Pinned method",
        assumption_checks=["split integrity"],
        evaluation_metrics=["RMSE"] if objective == "predict" else ["R-squared"],
        limitations=[],
        plan_hash="c" * 64,
    )


def _prediction_result() -> dict:
    return {
        "schema_version": "analysis_result.v1",
        "objective": "predict",
        "method": "Random forest",
        "input_row_count": 10,
        "analyzed_row_count": 10,
        "preprocessing_applied": [],
        "assumption_checks": [{"name": "split integrity", "passed": True}],
        "metrics": [{"name": "RMSE", "value": 1.25}],
        "statistical_results": [],
        "warnings": [],
        "limitations": [],
        "artifact_refs": ["analysis_result.json"],
        "narrative": ["Performance was evaluated on a held-out test set."],
        "prediction_diagnostics": {
            "target_column": "outcome",
            "feature_columns": ["predictor"],
            "train_row_count": 7,
            "test_row_count": 3,
            "train_row_ids": [str(index) for index in range(7)],
            "test_row_ids": [str(index) for index in range(7, 10)],
        },
    }


def _validate(payload: dict, *, plan: AnalysisPlanVersion | None = None):
    return ResultValidator().validate(
        raw_result=json.dumps(payload, separators=(",", ":")).encode(),
        plan=plan or _plan(),
        profile=_profile(),
        artifact_filenames={"analysis_result.json"},
    )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda value: value["prediction_diagnostics"]["feature_columns"].append("outcome"),
            "target leakage",
        ),
        (
            lambda value: value["prediction_diagnostics"]["test_row_ids"].append("0"),
            "train/test contamination",
        ),
        (
            lambda value: value["prediction_diagnostics"].update(
                {"train_row_count": 6, "train_row_ids": [str(index) for index in range(6)]}
            ),
            "must equal analyzed_row_count",
        ),
        (lambda value: value.__setitem__("metrics", [{"name": "Accuracy", "value": 1}]), "not approved"),
    ],
)
def test_prediction_leakage_contamination_and_wrong_metrics_are_rejected(mutate, expected) -> None:
    payload = _prediction_result()
    mutate(payload)

    with pytest.raises(ResultValidationError, match=expected):
        _validate(payload)


def test_p_value_requires_effect_size_and_confidence_interval() -> None:
    payload = _prediction_result()
    payload["statistical_results"] = [{"name": "coefficient", "p_value": 0.02}]

    with pytest.raises(ResultValidationError, match="effect_size and confidence_interval"):
        _validate(payload)

    payload["statistical_results"][0].update(
        {"effect_size": 0.4, "confidence_interval": [0.1, 0.7]}
    )
    assert _validate(payload).result_hash

    payload["statistical_results"][0]["p_value"] = 1.2
    with pytest.raises(ResultValidationError, match="between 0 and 1"):
        _validate(payload)

    payload["statistical_results"][0].update(
        {"p_value": 0.02, "effect_size": 2.0, "confidence_interval": [0.1, 0.7]}
    )
    with pytest.raises(ResultValidationError, match="inside confidence_interval"):
        _validate(payload)


def test_result_hash_is_canonical_and_secret_or_host_paths_are_rejected() -> None:
    payload = _prediction_result()
    first = ResultValidator().validate(
        raw_result=json.dumps(payload, sort_keys=False).encode(),
        plan=_plan(),
        profile=_profile(),
        artifact_filenames={"analysis_result.json"},
    )
    second = ResultValidator().validate(
        raw_result=json.dumps(payload, sort_keys=True).encode(),
        plan=_plan(),
        profile=_profile(),
        artifact_filenames={"analysis_result.json"},
    )
    assert first.result_hash == second.result_hash

    payload["limitations"] = ["debug file: /etc/passwd"]
    with pytest.raises(ResultValidationError, match="path or secret-like value"):
        _validate(payload)
