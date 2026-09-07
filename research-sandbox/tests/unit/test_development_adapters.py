import json

import pytest
from sandbox_service.adapters.development import (
    DeterministicProjectAIClient,
    create_demo_graph_snapshot_reader,
    create_demo_project_ai_client,
)
from sandbox_service.code_policy import CodePolicyChecker


def test_demo_factories_are_explicit_and_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_ENVIRONMENT", "development")
    monkeypatch.delenv("SANDBOX_DEMO_MODE", raising=False)
    with pytest.raises(RuntimeError, match="SANDBOX_DEMO_MODE=true"):
        create_demo_project_ai_client()

    monkeypatch.setenv("SANDBOX_DEMO_MODE", "true")
    assert create_demo_project_ai_client() is not None
    assert create_demo_graph_snapshot_reader() is not None

    monkeypatch.setenv("SANDBOX_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="development Sandbox adapters"):
        create_demo_project_ai_client()


@pytest.mark.asyncio
async def test_demo_ai_generates_policy_compliant_code_without_raw_rows() -> None:
    client = DeterministicProjectAIClient()
    generated = await client.invoke_structured(
        project_id="project-a",
        operation="code_generation",
        prompt_version="analysis.code_generation.v1",
        input_payload={
            "approved_plan": {
                "objective": "describe",
                "method": "Thống kê mô tả xác định",
                "outcome_columns": ["price per fruit ($)"],
                "predictor_columns": ["count sold", "fruit name"],
            },
            "dataset_profile": {"row_count": 3, "columns": [{"name": "score"}]},
        },
        output_schema=dict,
        correlation_id="correlation-a",
    )
    source = generated["source_code"]
    assert CodePolicyChecker().check(source).allowed is True
    assert "raw_rows" not in source
    assert "read_csv" not in source
    for required_import in (
        "import pandas as pd",
        "import numpy as np",
        "import json",
        "import pathlib",
    ):
        assert required_import in source
    assert "df[col_name]" in source
    assert "df.price" not in source and "df.count" not in source
    assert "/workspace/output/analysis_result.json" in source
    assert "/workspace/output/tables/summary.csv" in source
    assert "/workspace/output/charts/analysis.png" in source
    assert "emit_table('summary', summary)" in source
    assert "emit_chart('analysis', figure)" in source


@pytest.mark.asyncio
async def test_demo_ai_association_chart_includes_fitted_trend_line() -> None:
    client = DeterministicProjectAIClient()
    generated = await client.invoke_structured(
        project_id="project-a",
        operation="code_generation",
        prompt_version="analysis.code_generation.v1",
        input_payload={
            "approved_plan": {
                "objective": "associate",
                "method": "Hồi quy tuyến tính",
                "outcome_columns": ["reaction_time_ms"],
                "predictor_columns": ["sleep_hours"],
                "output_language": "vi",
            },
            "dataset_profile": {"row_count": 60},
        },
        output_schema=dict,
        correlation_id="correlation-trend",
    )

    source = generated["source_code"]
    assert "axis.scatter" in source
    assert "np.polyfit" in source
    assert "axis.plot(trend_x, trend_y" in source
    assert "Đường xu hướng" in source
    assert CodePolicyChecker().check(source).allowed is True


@pytest.mark.asyncio
async def test_demo_ai_result_interpretation_contains_no_uncited_numbers() -> None:
    client = DeterministicProjectAIClient()
    generated = await client.invoke_structured(
        project_id="project-a",
        operation="result_interpretation",
        prompt_version="analysis.result_interpretation.v1",
        input_payload={"validated_result": json.loads('{"metrics": []}')},
        output_schema=dict,
        correlation_id="correlation-a",
    )
    assert generated["numeric_claims"] == []
    assert all(not any(character.isdigit() for character in text) for text in generated["narrative"])
