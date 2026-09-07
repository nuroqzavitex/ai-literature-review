from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, ConfigDict
from sandbox_service.adapters.project_ai import (
    ProjectAIHTTPClient,
    ProjectAIProvider,
    create_project_ai_client,
)
from sandbox_service.code_policy import CodePolicyChecker
from sandbox_service.domain.errors import ProjectAIUnavailable
from sandbox_service.domain.execution import GeneratedCode


class _StructuredAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    limitations: list[str]


@pytest.mark.asyncio
async def test_gemini_uses_json_schema_and_validates_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.headers["x-goog-api-key"] == "google-test-key"
        body = json.loads(request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["responseJsonSchema"]["required"] == [
            "answer",
            "limitations",
        ]
        prompt = json.loads(body["contents"][0]["parts"][0]["text"])
        assert prompt["prompt_version"] == "sandbox.hypothesis_generation.v1"
        assert prompt["input_payload"] == {"context": {"evidence_refs": ["paper-1"]}}
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "answer": "Giả thuyết có thể kiểm định",
                                            "limitations": ["Cần reviewer xác nhận"],
                                        }
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ProjectAIHTTPClient(
            providers=(
                ProjectAIProvider(
                    name="google",
                    model="gemini-test",
                    api_keys=("google-test-key",),
                    base_url="https://generativelanguage.googleapis.com/v1beta",
                ),
            ),
            http_client=http_client,
        )
        result = await client.invoke_structured(
            project_id="project-1",
            operation="hypothesis_generation",
            prompt_version="sandbox.hypothesis_generation.v1",
            input_payload={"context": {"evidence_refs": ["paper-1"]}},
            output_schema=_StructuredAnswer,
            correlation_id="correlation-1",
        )

    assert result == {
        "answer": "Giả thuyết có thể kiểm định",
        "limitations": ["Cần reviewer xác nhận"],
    }


@pytest.mark.asyncio
async def test_provider_failover_reaches_ollama_without_exposing_keys(caplog) -> None:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host or "")
        if request.url.host == "google.invalid":
            return httpx.Response(503, json={"error": "unavailable"})
        assert request.url == httpx.URL("https://ollama.invalid/v1/chat/completions")
        assert request.headers["authorization"] == "Bearer ollama-secret-value"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"answer":"fallback ok","limitations":[]}'
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ProjectAIHTTPClient(
            providers=(
                ProjectAIProvider(
                    name="google",
                    model="gemini-test",
                    api_keys=("google-secret-value",),
                    base_url="https://google.invalid/v1beta",
                ),
                ProjectAIProvider(
                    name="ollama",
                    model="ollama-test",
                    api_keys=("ollama-secret-value",),
                    base_url="https://ollama.invalid",
                ),
            ),
            http_client=http_client,
        )
        result = await client.invoke_structured(
            project_id="project-1",
            operation="plan_generation",
            prompt_version="analysis.plan_generation.v1",
            input_payload={"dataset_profile": {"row_count": 10}},
            output_schema=_StructuredAnswer,
            correlation_id="correlation-2",
        )

    assert calls == ["google.invalid", "ollama.invalid"]
    assert result["answer"] == "fallback ok"
    assert "google-secret-value" not in caplog.text
    assert "ollama-secret-value" not in caplog.text


@pytest.mark.asyncio
async def test_invalid_structured_output_fails_closed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"answer":"missing field"}'}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ProjectAIHTTPClient(
            providers=(
                ProjectAIProvider(
                    name="ollama",
                    model="ollama-test",
                    api_keys=("test-key",),
                    base_url="https://ollama.invalid/v1",
                ),
            ),
            http_client=http_client,
        )
        with pytest.raises(ProjectAIUnavailable) as raised:
            await client.invoke_structured(
                project_id="project-1",
                operation="plan_generation",
                prompt_version="analysis.plan_generation.v1",
                input_payload={},
                output_schema=_StructuredAnswer,
                correlation_id="correlation-3",
            )

    assert raised.value.retryable is True
    assert raised.value.details == {"attempted_providers": ["ollama"]}


def test_factory_reads_google_alias_without_leaking_secret(monkeypatch) -> None:
    for name in (
        "GOOGLE_API_KEYS",
        "GOOGLE_API_KEY",
        "OLLAMA_API_KEYS",
        "OLLAMA_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-alias-secret")
    monkeypatch.setenv("SANDBOX_AI_PROVIDER", "google")

    client = create_project_ai_client()

    assert "gemini-alias-secret" not in repr(client._providers[0])
    assert client._providers[0].name == "google"


def test_code_generation_prompt_enforces_safe_columns_and_fixed_artifacts() -> None:
    prompt = ProjectAIHTTPClient._prompt(
        operation="code_generation",
        prompt_version="analysis.code_generation.v1",
        input_payload={
            "approved_plan": {
                "outcome_columns": ["price per fruit ($)"],
                "predictor_columns": ["count sold", "fruit name"],
            }
        },
        output_schema={"type": "object"},
    )

    contract = json.loads(prompt)["python_runtime_contract"]
    assert contract["required_imports"] == ["pandas", "numpy", "json", "pathlib"]
    assert "df[col_name]" in contract["column_access"]
    assert "df.<column>" in contract["column_access"]
    assert contract["required_artifacts"] == [
        "/workspace/output/analysis_result.json",
        "/workspace/output/tables/summary.csv",
        "/workspace/output/charts/analysis.png",
    ]
    assert "emit_chart('analysis', figure)" in contract["required_sdk_calls"]
    assert "p_value" in contract["analysis_result_rules"]
    assert "effect_size" in contract["analysis_result_rules"]
    assert "confidence_interval" in contract["analysis_result_rules"]
    assert "same scale" in contract["analysis_result_rules"]
    assert "scatter-only chart is forbidden" in contract["chart_rule"]
    assert "fitted trend/regression line" in contract["chart_rule"]


def test_prompt_pins_vietnamese_for_human_readable_ai_output() -> None:
    prompt = ProjectAIHTTPClient._prompt(
        operation="plan_generation",
        prompt_version="analysis.plan_generation.v1",
        input_payload={"output_language": "vi", "dataset_profile": {"row_count": 3}},
        output_schema={"type": "object"},
    )

    contract = json.loads(prompt)["output_language_contract"]
    assert "Vietnamese" in contract
    assert "dataset column names" in contract


@pytest.mark.asyncio
async def test_live_code_generation_injects_sdk_import_when_model_omits_it() -> None:
    model_source = """df = load_dataset()
summary = df.describe(include='all').reset_index()
emit_table('summary', summary)
emit_result({'schema_version': 'analysis_result.v1'})
"""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"source_code": model_source})
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = ProjectAIHTTPClient(
            providers=(
                ProjectAIProvider(
                    name="ollama",
                    model="ollama-test",
                    api_keys=("test-key",),
                    base_url="https://ollama.invalid/v1",
                ),
            ),
            http_client=http_client,
        )
        result = await client.invoke_structured(
            project_id="project-1",
            operation="code_generation",
            prompt_version="analysis.code_generation.v1",
            input_payload={"approved_plan": {}, "dataset_profile": {}},
            output_schema=GeneratedCode,
            correlation_id="correlation-code-import",
        )

    source = result["source_code"]
    assert "emit_analysis_result as sandbox_emit_analysis_result" in source
    assert "from sandbox_sdk import emit_chart, emit_table, load_dataset" in source
    assert "def emit_result(result_dict):" in source
    assert source.index("load_dataset") < source.index("df = load_dataset()")
    assert CodePolicyChecker().check(source).allowed is True


def test_live_code_generation_pins_result_contract_and_removes_model_override() -> None:
    decoded = {
        "source_code": """from sandbox_sdk import emit_result, emit_table, load_dataset
df = load_dataset()
summary = df.describe(include='all').reset_index()
emit_table('summary', summary)
emit_result({
    'schema_version': '1.0',
    'input_row_count': len(df),
    'analyzed_row_count': len(df),
    'assumption_checks': ['checked missing values'],
    'metrics': ['Mean of price per fruit ($)'],
    'narrative': 'Descriptive result',
    'prediction_diagnostics': {},
})
"""
    }
    payload = {
        "approved_plan": {
            "objective": "describe",
            "method": "Descriptive aggregation",
            "preprocessing_steps": ["Check missing values"],
            "assumption_checks": ["Dataset is non-empty"],
            "evaluation_metrics": ["Mean of price per fruit ($)"],
            "limitations": ["Descriptive analysis only"],
        }
    }

    normalized = ProjectAIHTTPClient._normalize_generated_code_response(
        operation="code_generation", decoded=decoded, input_payload=payload
    )["source_code"]

    assert normalized.count("def emit_result(result_dict):") == 1
    assert "objective='describe'" in normalized
    assert "method='Descriptive aggregation'" in normalized
    assert "from sandbox_sdk import emit_result" not in normalized
    assert CodePolicyChecker().check(normalized).allowed is True


def test_live_code_generation_repairs_json_literals_inside_python_only() -> None:
    decoded = {
        "source_code": '''df = load_dataset()
label = "keep null, true and false as narrative text"
emit_result({
    "input_row_count": len(df),
    "analyzed_row_count": len(df),
    "assumption_checks": [{"name": label, "passed": true}],
    "metrics": [],
    "statistical_results": [],
    "warnings": [],
    "limitations": [],
    "artifact_refs": [],
    "narrative": [label],
    "prediction_diagnostics": null,
    "optional_flag": false,
})
'''
    }

    normalized = ProjectAIHTTPClient._normalize_generated_code_response(
        operation="code_generation", decoded=decoded, input_payload={}
    )["source_code"]

    compile(normalized, "<generated-code>", "exec")
    assert "'prediction_diagnostics': None" in normalized
    assert "'passed': True" in normalized
    assert "'optional_flag': False" in normalized
    assert "keep null, true and false as narrative text" in normalized
    assert CodePolicyChecker().check(normalized).allowed is True


def test_live_code_generation_discards_model_copy_of_trusted_result_wrapper() -> None:
    copied_wrapper = ProjectAIHTTPClient._generated_code_preamble(
        {
            "approved_plan": {
                "objective": "describe",
                "method": "Descriptive aggregation",
                "evaluation_metrics": ["Mean"],
            }
        }
    )
    decoded = {
        "source_code": f"""{copied_wrapper}

df = load_dataset()
summary = df.describe(include='all').reset_index()
emit_table('summary', summary)
emit_result({{
    'input_row_count': len(df),
    'analyzed_row_count': len(df),
    'assumption_checks': ['dataset checked'],
}})
"""
    }

    normalized = ProjectAIHTTPClient._normalize_generated_code_response(
        operation="code_generation",
        decoded=decoded,
        input_payload={
            "approved_plan": {
                "objective": "describe",
                "method": "Descriptive aggregation",
                "evaluation_metrics": ["Mean"],
            }
        },
    )["source_code"]

    assert normalized.count("def emit_result(result_dict):") == 1
    assert "return emit_result(result_dict, objective=" not in normalized
    assert normalized.count("emit_result({") == 1
    assert CodePolicyChecker().check(normalized).allowed is True


def test_live_code_generation_replaces_standard_main_guard_without_relaxing_policy() -> None:
    decoded = {
        "source_code": """def main():
    df = load_dataset()
    summary = df.describe(include='all').reset_index()
    emit_table('summary', summary)
    emit_result({'schema_version': 'analysis_result.v1'})

if __name__ == '__main__':
    main()
"""
    }

    normalized = ProjectAIHTTPClient._normalize_generated_code_response(
        operation="code_generation", decoded=decoded
    )["source_code"]

    assert "__name__" not in normalized
    assert normalized.rstrip().endswith("main()")
    assert CodePolicyChecker().check(normalized).allowed is True


def test_live_code_generation_does_not_remove_nonstandard_dunder_condition() -> None:
    decoded = {
        "source_code": """if __name__ != '__main__':
    emit_result({'schema_version': 'analysis_result.v1'})
"""
    }

    normalized = ProjectAIHTTPClient._normalize_generated_code_response(
        operation="code_generation", decoded=decoded
    )["source_code"]

    result = CodePolicyChecker().check(normalized)
    assert "__name__" in normalized
    assert result.allowed is False
    assert any(item.rule == "reflection" for item in result.violations)
