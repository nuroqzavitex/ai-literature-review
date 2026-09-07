from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src.agents.litreview.workflow.nodes import (
    _is_provider_failover_error,
    _is_schema_capability_error,
    _is_structured_output_error,
    _parse_prompted_json,
    _StructuredLLMInvoker,
)
from src.config import Settings
from src.services.llm import _build_client, _configured_endpoints


class _Prompt:
    def __or__(self, structured_llm):
        return structured_llm

    def format_messages(self, **_inputs):
        return ["prompt"]


class _UnavailableLLM:
    def __init__(self):
        self.calls = 0

    def with_structured_output(self, _schema):
        return self

    async def ainvoke(self, _inputs):
        self.calls += 1
        raise RuntimeError("API_KEY_INVALID: API key not valid")


class _WorkingLLM:
    def __init__(self):
        self.calls = 0

    def with_structured_output(self, _schema):
        return self

    async def ainvoke(self, _inputs):
        self.calls += 1
        return {"provider": "fallback"}


class _StructuredResult(BaseModel):
    value: str


class _InvalidJSONLLM:
    def __init__(self):
        self.calls = 0

    def with_structured_output(self, _schema):
        return self

    async def ainvoke(self, _inputs):
        self.calls += 1
        return _StructuredResult.model_validate_json("not-json")


class _PromptJSONLLM:
    native_schema_supported = False

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.raw_calls = 0
        self.native_calls = 0
        self.messages = []

    def with_structured_output(self, _schema):
        self.native_calls += 1
        raise AssertionError("Prompt-JSON candidate must not request native response_format")

    async def ainvoke(self, _messages):
        self.raw_calls += 1
        self.messages.append(_messages)
        return SimpleNamespace(content=self.responses.pop(0))


class _CapabilityDowngradeLLM:
    native_schema_supported = True

    def __init__(self):
        self.native_calls = 0
        self.raw_calls = 0

    def with_structured_output(self, _schema):
        self.native_calls += 1
        return self

    async def ainvoke(self, _messages):
        self.raw_calls += 1
        if self.raw_calls == 1:
            raise RuntimeError("response_format type is unavailable now")
        return SimpleNamespace(content='{"value":"downgraded"}')


@pytest.mark.asyncio
async def test_structured_invoker_rotates_to_configured_fallback(monkeypatch):
    primary = _UnavailableLLM()
    fallback = _WorkingLLM()
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm", lambda: primary)
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm_fallbacks", lambda: [fallback])

    invoker = _StructuredLLMInvoker(_Prompt(), object, "test")

    assert await invoker.ainvoke({"batch": 1}) == {"provider": "fallback"}
    assert await invoker.ainvoke({"batch": 2}) == {"provider": "fallback"}
    assert primary.calls == 1
    assert fallback.calls == 2


@pytest.mark.asyncio
async def test_structured_invoker_does_not_fail_over_for_schema_error(monkeypatch):
    class SchemaFailure(_UnavailableLLM):
        async def ainvoke(self, _inputs):
            self.calls += 1
            raise ValueError("Pydantic validation failed for structured output")

    primary = SchemaFailure()
    fallback = _WorkingLLM()
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm", lambda: primary)
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm_fallbacks", lambda: [fallback])

    invoker = _StructuredLLMInvoker(_Prompt(), object, "test")

    with pytest.raises(ValueError, match="Pydantic validation failed"):
        await invoker.ainvoke({"batch": 1})
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_structured_invoker_retries_invalid_json_then_uses_fallback(monkeypatch):
    primary = _InvalidJSONLLM()
    fallback = _WorkingLLM()
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm", lambda: primary)
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm_fallbacks", lambda: [fallback])

    invoker = _StructuredLLMInvoker(_Prompt(), _StructuredResult, "test")

    assert await invoker.ainvoke({"batch": 1}) == {"provider": "fallback"}
    assert primary.calls == 2
    assert fallback.calls == 1


def test_pydantic_invalid_json_is_a_structured_output_error():
    with pytest.raises(Exception) as captured:
        _StructuredResult.model_validate_json("entails=True")

    assert _is_structured_output_error(captured.value)


@pytest.mark.asyncio
async def test_prompt_json_candidate_skips_native_schema_and_validates_response(monkeypatch):
    client = _PromptJSONLLM(['{"value":"valid"}'])
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm", lambda: client)
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm_fallbacks", lambda: [])

    result = await _StructuredLLMInvoker(_Prompt(), _StructuredResult, "test").ainvoke({"batch": 1})

    assert result == _StructuredResult(value="valid")
    assert client.native_calls == 0
    assert client.raw_calls == 1


@pytest.mark.asyncio
async def test_response_format_capability_error_downgrades_same_provider(monkeypatch):
    client = _CapabilityDowngradeLLM()
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm", lambda: client)
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm_fallbacks", lambda: [])

    invoker = _StructuredLLMInvoker(_Prompt(), _StructuredResult, "test")
    result = await invoker.ainvoke({"batch": 1})
    repeated_result = await invoker.ainvoke({"batch": 2})

    assert result == _StructuredResult(value="downgraded")
    assert repeated_result == _StructuredResult(value="downgraded")
    assert client.native_calls == 1
    assert client.raw_calls == 3


@pytest.mark.asyncio
async def test_invalid_prompt_json_retries_once_then_uses_next_provider(monkeypatch):
    invalid = _PromptJSONLLM(["not-json", "still-not-json"])
    fallback = _PromptJSONLLM(['{"value":"fallback"}'])
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm", lambda: invalid)
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm_fallbacks", lambda: [fallback])

    result = await _StructuredLLMInvoker(_Prompt(), _StructuredResult, "test").ainvoke({"batch": 1})

    assert result == _StructuredResult(value="fallback")
    assert invalid.raw_calls == 2
    assert fallback.raw_calls == 1


@pytest.mark.asyncio
async def test_invalid_prompt_json_retries_with_an_explicit_repair_prompt(monkeypatch):
    client = _PromptJSONLLM(["not-json", '{"value":"repaired"}'])
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm", lambda: client)
    monkeypatch.setattr("src.agents.litreview.workflow.nodes.get_llm_fallbacks", lambda: [])

    result = await _StructuredLLMInvoker(_Prompt(), _StructuredResult, "test").ainvoke({"batch": 1})

    assert result == _StructuredResult(value="repaired")
    assert client.raw_calls == 2
    assert "previous output was invalid" in client.messages[1][0].content.lower()


def test_prompted_json_parser_accepts_one_json_fence_and_rejects_extra_text():
    assert _parse_prompted_json('```json\n{"value":"valid"}\n```', _StructuredResult) == _StructuredResult(
        value="valid"
    )
    with pytest.raises(Exception, match="invalid JSON"):
        _parse_prompted_json('Here is the result: {"value":"invalid"}', _StructuredResult)
    with pytest.raises(Exception, match="required schema"):
        _parse_prompted_json('{"value":"invalid","unexpected":true}', _StructuredResult)


def test_response_format_unavailable_is_a_schema_capability_error():
    assert _is_schema_capability_error(RuntimeError("response_format type is unavailable now"))


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "app_env": "development",
        "llm_provider": "auto",
        "llm_model": "gemini-2.5-flash",
        "llm_api_key": "",
        "google_api_key": "",
        "google_api_keys": "",
        "google_model": "gemini-2.5-flash",
        "openai_api_key": "",
        "openai_api_keys": "",
        "openai_model": "gpt-4o",
        "ollama_api_key": "",
        "ollama_api_keys": "",
        "ollama_model": "gemma4:31b-cloud",
        "ollama_host": "https://ollama.com",
        "opencode_api_key": "",
        "opencode_api_keys": "",
        "opencode_model": "deepseek-v4-flash-free",
        "opencode_host": "https://opencode.ai/zen/v1",
        "openrouter_api_key": "",
        "openrouter_api_keys": "",
        "openrouter_model": "openrouter/auto",
        "openrouter_host": "https://openrouter.ai/api/v1",
        "llm_failover_enabled": True,
        "llm_fallback_order": "ollama,google,openai,openrouter",
    }
    values.update(overrides)
    return Settings(**values)


def test_auto_uses_only_complete_providers_in_configured_order():
    settings = _settings(
        llm_fallback_order="openrouter,google,openai,ollama",
        openrouter_api_keys="or-key-1,or-key-2",
        google_api_key="google-key",
    )

    endpoints = _configured_endpoints(settings)

    assert [endpoint.label for endpoint in endpoints] == [
        "openrouter:openrouter/auto",
        "openrouter:openrouter/auto",
        "google:gemini-2.5-flash",
    ]


def test_auto_skips_provider_with_missing_required_host():
    settings = _settings(
        llm_fallback_order="openrouter,google",
        openrouter_api_key="or-key",
        openrouter_host="",
        google_api_key="google-key",
    )

    endpoints = _configured_endpoints(settings)

    assert [endpoint.provider for endpoint in endpoints] == ["google"]


def test_auto_routes_to_opencode_as_an_openai_compatible_provider():
    settings = _settings(
        llm_fallback_order="opencode,google",
        opencode_api_keys="opencode-key-1,opencode-key-2",
        google_api_key="google-key",
    )

    endpoints = _configured_endpoints(settings)

    assert [endpoint.label for endpoint in endpoints] == [
        "opencode:deepseek-v4-flash-free",
        "opencode:deepseek-v4-flash-free",
        "google:gemini-2.5-flash",
    ]
    assert endpoints[0].host == "https://opencode.ai/zen/v1"


def test_opencode_client_uses_its_openai_compatible_host(monkeypatch):
    settings = _settings(
        llm_provider="opencode",
        opencode_api_key="opencode-key",
    )
    endpoint = _configured_endpoints(settings)[0]
    captured = {}

    def fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("src.services.llm.ChatOpenAI", fake_chat_openai)

    _build_client(endpoint, settings)

    assert captured["model"] == "deepseek-v4-flash-free"
    assert captured["base_url"] == "https://opencode.ai/zen/v1"


def test_explicit_provider_never_crosses_to_another_provider():
    settings = _settings(
        llm_provider="openrouter",
        openrouter_api_key="or-key",
        google_api_key="google-key",
        llm_fallback_order="google,openrouter",
    )

    endpoints = _configured_endpoints(settings)

    assert [endpoint.provider for endpoint in endpoints] == ["openrouter"]


def test_explicit_provider_fails_fast_when_incomplete():
    settings = _settings(
        llm_provider="openrouter",
        openrouter_api_key="",
        openrouter_api_keys="",
    )

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        _configured_endpoints(settings)


def test_openrouter_rejects_ollama_style_model_slug():
    settings = _settings(
        llm_provider="openrouter",
        openrouter_api_key="or-key",
        openrouter_model="gemma4:31b-cloud",
    )

    with pytest.raises(ValueError, match="OPENROUTER_MODEL"):
        _configured_endpoints(settings)


def test_auto_skips_provider_with_invalid_model_slug():
    settings = _settings(
        llm_provider="auto",
        llm_fallback_order="openrouter,google",
        openrouter_api_key="or-key",
        openrouter_model="gemma4:31b-cloud",
        google_api_key="google-key",
    )

    endpoints = _configured_endpoints(settings)

    assert [endpoint.provider for endpoint in endpoints] == ["google"]


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 401 - Unauthorized",
        "status code 403: Forbidden",
        "status code 429: Too Many Requests",
    ],
)
def test_provider_http_failures_are_eligible_for_failover(message):
    assert _is_provider_failover_error(RuntimeError(message))
