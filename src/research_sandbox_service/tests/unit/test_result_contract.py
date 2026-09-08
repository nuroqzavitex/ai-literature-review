from __future__ import annotations

import json

import numpy as np

from sandbox_sdk import emit_analysis_result
from sandbox_service.domain.analysis_plans import AnalysisPlanVersion
from sandbox_service.domain.datasets import DatasetProfile
from sandbox_service.domain.results import AnalysisResult
from sandbox_service.execution.result_validator import ResultValidator


def test_generated_result_contract_normalizes_live_llm_shape(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SANDBOX_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("SANDBOX_MAX_OUTPUT_BYTES", "1048576")

    result_path = emit_analysis_result(
        {
            "schema_version": "1.0",
            "objective": "made-up-objective",
            "method": "model-selected method",
            "input_row_count": 100,
            "analyzed_row_count": 100,
            "preprocessing_applied": "Checked missing values",
            "assumption_checks": [
                "Checked for missing values: 0 found",
                "Assessed count sold distribution",
            ],
            "metrics": [
                "Sum of count sold per fruit name",
                "Mean of price per fruit ($) per fruit name",
            ],
            "statistical_results": [],
            "warnings": "No warnings",
            "limitations": "Descriptive result only",
            "artifact_refs": ["tables/summary.csv"],
            "narrative": "The analysis aggregated sales by fruit category.",
            "prediction_diagnostics": {},
            "unexpected_model_field": "discarded",
        },
        objective="describe",
        method="Descriptive statistical aggregation grouped by fruit name",
        preprocessing_steps=["Check missing values"],
        planned_assumption_checks=["Dataset is non-empty"],
        planned_metrics=[
            "Sum of count sold per fruit name",
            "Mean of price per fruit ($) per fruit name",
        ],
        planned_limitations=["No causal interpretation"],
    )

    raw = json.loads(result_path.read_text(encoding="utf-8"))
    pretty_text = result_path.read_text(encoding="utf-8")
    result = AnalysisResult.model_validate(raw)

    assert result.schema_version == "analysis_result.v1"
    assert result.objective == "describe"
    assert result.method == "Descriptive statistical aggregation grouped by fruit name"
    assert result.assumption_checks[0] == {
        "name": "Checked for missing values: 0 found",
        "passed": None,
    }
    assert result.metrics[0].name == "Sum of count sold per fruit name"
    assert result.metrics[0].value is None
    assert result.narrative == ["The analysis aggregated sales by fruit category."]
    assert result.prediction_diagnostics is None
    assert "unexpected_model_field" not in raw
    assert pretty_text.endswith("\n")
    assert '\n  "schema_version": "analysis_result.v1"' in pretty_text
    assert len(pretty_text.splitlines()) > 10

    plan = AnalysisPlanVersion(
        project_id="project-a",
        dataset_id="dataset-a",
        question_id="question-a",
        question_version=1,
        profile_version=1,
        objective="describe",
        research_question="Summarize fruit sales by category",
        outcome_columns=["count sold", "price per fruit ($)"],
        predictor_columns=[],
        group_columns=["fruit name"],
        covariate_columns=[],
        method="Descriptive statistical aggregation grouped by fruit name",
        method_rationale="Approved aggregation",
        preprocessing_steps=["Check missing values"],
        assumption_checks=["Dataset is non-empty"],
        evaluation_metrics=[
            "Sum of count sold per fruit name",
            "Mean of price per fruit ($) per fruit name",
        ],
        limitations=["No causal interpretation"],
        plan_hash="a" * 64,
    )
    profile = DatasetProfile(
        dataset_id="dataset-a",
        project_id="project-a",
        version=1,
        content_hash="b" * 64,
        row_count=100,
        column_count=0,
        columns=[],
        profile_hash="c" * 64,
    )

    validated = ResultValidator().validate(
        raw_result=result_path.read_bytes(),
        plan=plan,
        profile=profile,
        artifact_filenames={"tables/summary.csv"},
    )
    assert validated.result_hash


def test_live_fruit_result_passes_scientific_and_lineage_validation(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("SANDBOX_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("SANDBOX_MAX_OUTPUT_BYTES", "1048576")
    approved_metrics = [
        "Sum of 'count sold' per fruit name",
        "Mean of 'price per fruit ($)' per fruit name",
        "Min and Max of 'price per fruit ($)' per fruit name",
    ]
    method = "Descriptive statistical aggregation grouped by fruit name."

    result_path = emit_analysis_result(
        {
            "input_row_count": 8,
            "analyzed_row_count": 8,
            "assumption_checks": [
                {"name": "Data Consistency", "passed": np.bool_(True)},
                {"name": "Distribution Appropriateness", "passed": False},
            ],
            "metrics": [
                {"name": "Total Sold", "value": 638.0},
                {"name": "Average Price", "value": 0.42},
            ],
            "statistical_results": [
                {
                    "fruit": np.str_("apple"),
                    "total_sold": np.int64(0),
                    "average_price": np.float64(0.8),
                },
                {
                    "fruit": np.str_("grape"),
                    "total_sold": np.int64(355),
                    "average_price": np.float64(0.06),
                },
            ],
            "warnings": [],
            "limitations": ["The small sample size (8 rows) may increase variance."],
            "artifact_refs": ["/workspace/output/tables/summary.csv"],
            "narrative": [
                "The analysis aggregated sales data for 6 unique fruit types.",
                "Total quantity sold and average unit price were calculated per category.",
            ],
            "prediction_diagnostics": {},
        },
        objective="describe",
        method=method,
        planned_assumption_checks=["Data consistency"],
        planned_metrics=approved_metrics,
        planned_limitations=["Descriptive analysis only"],
    )

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["metrics"] == []
    assert payload["artifact_refs"] == ["tables/summary.csv"]
    assert payload["narrative"] == [
        "Total quantity sold and average unit price were calculated per category."
    ]

    plan = AnalysisPlanVersion(
        project_id="project-a",
        dataset_id="dataset-a",
        question_id="question-a",
        question_version=1,
        profile_version=1,
        objective="describe",
        research_question="Summarize fruit sales by category",
        outcome_columns=["count sold", "price per fruit ($)"],
        predictor_columns=[],
        group_columns=["fruit name"],
        covariate_columns=[],
        method=method,
        method_rationale="Approved aggregation",
        assumption_checks=["Data consistency"],
        evaluation_metrics=approved_metrics,
        limitations=["Descriptive analysis only"],
        plan_hash="d" * 64,
    )
    profile = DatasetProfile(
        dataset_id="dataset-a",
        project_id="project-a",
        version=1,
        content_hash="e" * 64,
        row_count=8,
        column_count=0,
        columns=[],
        profile_hash="f" * 64,
    )

    validated = ResultValidator().validate(
        raw_result=result_path.read_bytes(),
        plan=plan,
        profile=profile,
        artifact_filenames={"analysis_result.json", "tables/summary.csv"},
    )
    assert validated.result_hash


def test_result_contract_omits_non_scalar_metric_value(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SANDBOX_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("SANDBOX_MAX_OUTPUT_BYTES", "1048576")
    metric_name = "95% confidence interval for sleep_hours"

    result_path = emit_analysis_result(
        {
            "input_row_count": 60,
            "analyzed_row_count": 60,
            "assumption_checks": [{"name": "linearity", "passed": True}],
            "metrics": [
                {
                    "name": metric_name,
                    "value": [-23.89, -20.26],
                    "details": "interval is reported in statistical_results",
                }
            ],
            "statistical_results": [
                {
                    "variable": "sleep_hours",
                    "effect_size": -22.08,
                    "confidence_interval": [-23.89, -20.26],
                }
            ],
        },
        objective="associate",
        method="Multiple linear regression",
        planned_assumption_checks=["linearity"],
        planned_metrics=[metric_name],
    )

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    result = AnalysisResult.model_validate(payload)
    assert result.metrics[0].value is None
    assert result.metrics[0].details["non_scalar_value_omitted"] is True
    assert result.statistical_results[0]["confidence_interval"] == [-23.89, -20.26]
