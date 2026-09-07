"""LLM client construction and deterministic provider routing.

Routing rules:
- LLM_PROVIDER=auto: use LLM_FALLBACK_ORDER and keep only providers that have
  every required value (key, model, and host when applicable).
- LLM_PROVIDER=<provider>: use only that provider. Multiple keys may rotate,
  but the application never crosses to another provider.
- No endpoint or credential is invented at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from src.config import Settings, get_settings

_VALID_PROVIDERS = ("google", "openai", "ollama", "opencode", "openrouter")
_FAILOVER_ERROR_MARKERS = (
    "api_key_invalid",
    "api key not valid",
    "invalid api key",
    "invalid authentication",
    "authentication_error",
    "unauthenticated",
    "unauthorized",
    "forbidden",
    "permission_denied",
    "resource_exhausted",
    "rate limit",
    "too many requests",
    "status code 401",
    "status code 403",
    "status code 429",
    "error code: 401",
    "error code: 403",
    "status code 500",
    "status code 502",
    "status code 503",
    "service unavailable",
    "connection error",
    "connect timeout",
    "read timeout",
)
_SCHEMA_CAPABILITY_ERROR_MARKERS = (
    "response_format type is unavailable",
    "response_format is unavailable",
    "response_format is not supported",
    "response_format unsupported",
    "json_schema is not supported",
    "structured output is not supported",
    "structured outputs are not supported",
)


def is_provider_failover_error(error: Exception) -> bool:
    """Whether an LLM failure is transient/provider-specific and safe to fail over."""
    return any(marker in str(error).lower() for marker in _FAILOVER_ERROR_MARKERS)


def is_schema_capability_error(error: Exception) -> bool:
    """Whether a provider rejected its native structured-output capability."""
    message = str(error).lower()
    return any(marker in message for marker in _SCHEMA_CAPABILITY_ERROR_MARKERS) or (
        "googleinvalidrequesterror" in message and "invalid_argument" in message
    )


@dataclass(frozen=True)
class LLMEndpoint:
    """One configured model/key combination with a secret-safe repr."""

    provider: str
    model: str
    api_key: str = field(repr=False)
    host: str | None = None

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class LLMClientCandidate:
    """A configured client plus its known structured-output capability."""

    endpoint: LLMEndpoint
    client: Any = field(repr=False)
    native_schema_supported: bool

    def with_structured_output(self, *args, **kwargs):
        return self.client.with_structured_output(*args, **kwargs)

    async def ainvoke(self, *args, **kwargs):
        return await self.client.ainvoke(*args, **kwargs)


def _split_values(raw: str) -> list[str]:
    return [value.strip() for value in raw.split(",") if value.strip()]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _provider_keys(settings: Settings, provider: str) -> list[str]:
    singular = {
        "google": settings.google_api_key,
        "openai": settings.openai_api_key,
        "ollama": settings.ollama_api_key,
        "opencode": settings.opencode_api_key,
        "openrouter": settings.openrouter_api_key,
    }[provider]
    pool = {
        "google": settings.google_api_keys,
        "openai": settings.openai_api_keys,
        "ollama": settings.ollama_api_keys,
        "opencode": settings.opencode_api_keys,
        "openrouter": settings.openrouter_api_keys,
    }[provider]
    keys = _unique([singular, *_split_values(pool)])

    # LLM_API_KEY is supported only when its provider is unambiguous.
    if not keys and settings.llm_api_key:
        if settings.llm_provider == provider:
            keys = [settings.llm_api_key]
        elif settings.llm_provider == "auto":
            model = settings.llm_model.lower()
            if provider == "google" and model.startswith("gemini"):
                keys = [settings.llm_api_key]
            elif provider == "openai" and (model.startswith("gpt") or model.startswith(("o1", "o3", "o4"))):
                keys = [settings.llm_api_key]
    return keys


def _model_for_provider(settings: Settings, provider: str) -> str:
    model = {
        "google": settings.google_model,
        "openai": settings.openai_model,
        "ollama": settings.ollama_model,
        "opencode": settings.opencode_model,
        "openrouter": settings.openrouter_model,
    }[provider]
    return model.strip() or settings.llm_model.strip()


def _host_for_provider(settings: Settings, provider: str) -> str | None:
    if provider == "ollama":
        return settings.ollama_host.strip()
    if provider == "opencode":
        return settings.opencode_host.strip()
    if provider == "openrouter":
        return settings.openrouter_host.strip()
    return None


def _validate_provider_model(provider: str, model: str) -> None:
    model_lower = model.lower()
    if provider == "google" and (
        model_lower.startswith("gpt")
        or model_lower.startswith(("o1", "o3", "o4"))
        or model_lower.startswith("openrouter/")
    ):
        raise ValueError(f"GOOGLE_MODEL '{model}' is not a Gemini model.")
    if provider == "openai" and (model_lower.startswith("gemini") or model_lower.startswith("openrouter/")):
        raise ValueError(f"OPENAI_MODEL '{model}' is not a direct OpenAI model.")
    if provider == "openrouter" and "/" not in model:
        raise ValueError(
            f"OPENROUTER_MODEL '{model}' is invalid. "
            "Use an OpenRouter slug such as 'openrouter/auto' or 'author/model'."
        )


def _missing_configuration(settings: Settings, provider: str) -> list[str]:
    names = {
        "google": ("GOOGLE_API_KEY(S)", "GOOGLE_MODEL", None),
        "openai": ("OPENAI_API_KEY(S)", "OPENAI_MODEL", None),
        "ollama": ("OLLAMA_API_KEY(S)", "OLLAMA_MODEL", "OLLAMA_HOST"),
        "opencode": ("OPENCODE_API_KEY(S)", "OPENCODE_MODEL", "OPENCODE_HOST"),
        "openrouter": ("OPENROUTER_API_KEY(S)", "OPENROUTER_MODEL", "OPENROUTER_HOST"),
    }
    key_name, model_name, host_name = names[provider]
    missing = []
    if not _provider_keys(settings, provider):
        missing.append(key_name)
    if not _model_for_provider(settings, provider):
        missing.append(model_name)
    if host_name and not _host_for_provider(settings, provider):
        missing.append(host_name)
    return missing


def _configuration_errors(settings: Settings, provider: str) -> list[str]:
    errors = _missing_configuration(settings, provider)
    model = _model_for_provider(settings, provider)
    if model:
        try:
            _validate_provider_model(provider, model)
        except ValueError as exc:
            errors.append(str(exc))

    host = _host_for_provider(settings, provider)
    if host and not host.startswith(("http://", "https://")):
        errors.append(f"{provider.upper()}_HOST must start with http:// or https://")
    return errors


def _endpoint_for(settings: Settings, provider: str, api_key: str) -> LLMEndpoint:
    model = _model_for_provider(settings, provider)
    _validate_provider_model(provider, model)
    return LLMEndpoint(
        provider=provider,
        model=model,
        api_key=api_key,
        host=_host_for_provider(settings, provider),
    )


def _openai_compatible_base_url(host: str) -> str:
    normalized = host.rstrip("/")
    return normalized if normalized.endswith("/v1") else f"{normalized}/v1"


def _build_client(endpoint: LLMEndpoint, settings: Settings, *, temperature: float | None = None):
    resolved_temperature = settings.llm_temperature if temperature is None else temperature
    if endpoint.provider == "google":
        return ChatGoogleGenerativeAI(
            model=endpoint.model,
            google_api_key=endpoint.api_key,
            temperature=resolved_temperature,
            max_retries=settings.llm_max_retries,
            timeout=settings.llm_timeout,
        )

    kwargs = {
        "model": endpoint.model,
        "api_key": endpoint.api_key,
        "temperature": resolved_temperature,
        "max_retries": settings.llm_max_retries,
        "timeout": settings.llm_timeout,
    }
    if endpoint.provider in {"ollama", "opencode", "openrouter"}:
        kwargs["base_url"] = _openai_compatible_base_url(endpoint.host or "")
    if endpoint.provider == "openrouter":
        headers = {}
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        if settings.openrouter_app_name:
            headers["X-Title"] = settings.openrouter_app_name
        if headers:
            kwargs["default_headers"] = headers
    return ChatOpenAI(**kwargs)


def _supports_native_schema(endpoint: LLMEndpoint) -> bool:
    """Return known native JSON-Schema support for a configured endpoint.

    Unknown endpoints start in native mode.  The agent invoker can downgrade an
    endpoint at runtime when the provider explicitly rejects ``response_format``.
    This keeps the capability policy narrow and avoids declaring every model at
    an OpenAI-compatible gateway unsupported by default.
    """

    if endpoint.provider == "ollama" and "ollama.com" in (endpoint.host or "").lower():
        # Ollama Cloud documents that structured outputs are not supported.
        return False
    return not (endpoint.provider == "opencode" and endpoint.model.strip().lower() == "deepseek-v4-flash-free")


def _auto_provider_order(settings: Settings) -> list[str]:
    order = _split_values(settings.llm_fallback_order) or list(_VALID_PROVIDERS)
    invalid = [provider for provider in order if provider not in _VALID_PROVIDERS]
    if invalid:
        raise ValueError(
            "LLM_FALLBACK_ORDER only accepts google, openai, ollama, opencode, openrouter; "
            f"received: {', '.join(invalid)}"
        )
    return list(dict.fromkeys(order))


def _configured_endpoints(settings: Settings) -> list[LLMEndpoint]:
    if settings.llm_provider == "auto":
        providers = _auto_provider_order(settings)
        complete_providers = [provider for provider in providers if not _configuration_errors(settings, provider)]
        if not complete_providers:
            details = "; ".join(
                f"{provider}: {', '.join(_configuration_errors(settings, provider))}" for provider in providers
            )
            raise ValueError(f"No fully configured LLM provider for auto mode. Missing: {details}")
    else:
        providers = [settings.llm_provider]
        errors = _configuration_errors(settings, settings.llm_provider)
        if errors:
            raise ValueError(
                f"LLM_PROVIDER='{settings.llm_provider}' is invalid or incomplete. Details: {', '.join(errors)}"
            )
        complete_providers = providers

    endpoints = [
        _endpoint_for(settings, provider, api_key)
        for provider in complete_providers
        for api_key in _provider_keys(settings, provider)
    ]

    if not settings.llm_failover_enabled:
        return endpoints[:1]
    return endpoints


def get_llm(*, temperature: float | None = None):
    """Return the first complete provider selected by the routing policy.

    ``temperature`` is deliberately per invocation so specialised agent roles
    can be deterministic or more generative without changing the global route.
    """

    settings = get_settings()
    endpoint = _configured_endpoints(settings)[0]
    return LLMClientCandidate(
        endpoint=endpoint,
        client=_build_client(endpoint, settings, temperature=temperature),
        native_schema_supported=_supports_native_schema(endpoint),
    )


def get_llm_fallbacks() -> list:
    """Return remaining allowed clients.

    In auto mode these may span providers. With an explicit LLM_PROVIDER they
    contain only additional keys for that same provider.
    """

    settings = get_settings()
    if not settings.llm_failover_enabled:
        return []
    return [
        LLMClientCandidate(
            endpoint=endpoint,
            client=_build_client(endpoint, settings),
            native_schema_supported=_supports_native_schema(endpoint),
        )
        for endpoint in _configured_endpoints(settings)[1:]
    ]


def get_llm_route_status() -> list[dict[str, str]]:
    """Return the configured route without exposing credentials or key counts."""

    settings = get_settings()
    route = []
    seen = set()
    for endpoint in _configured_endpoints(settings):
        key = (endpoint.provider, endpoint.model)
        if key in seen:
            continue
        seen.add(key)
        route.append({"provider": endpoint.provider, "model": endpoint.model})
    return route
