import pytest
from pydantic import ValidationError

from sandbox_service.config import SandboxSettings
from sandbox_service.main import create_app
from sandbox_service.repositories import InMemorySandboxSessionRepository
from tests.fakes import FakeObjectStore


def production_values() -> dict[str, object]:
    return {
        "_env_file": None,
        "SANDBOX_ENVIRONMENT": "production",
        "SANDBOX_ENABLED": True,
        "SANDBOX_PERSISTENCE_BACKEND": "postgres",
        "SANDBOX_DATABASE_URL": "postgresql+psycopg://sandbox:secret@db/sandbox",
        "SANDBOX_OBJECT_STORAGE_BACKEND": "s3",
        "SANDBOX_OBJECT_STORAGE_BUCKET": "sandbox-artifacts",
        "SANDBOX_MANIFEST_SIGNING_KEY": "production-manifest-key-with-at-least-32-bytes",
        "SANDBOX_SERVICE_AUTH_KEY": "production-service-auth-key-with-at-least-32-bytes",
        "SANDBOX_CONTEXT_SIGNING_KEY": "production-context-signing-key-at-least-32-bytes",
        "SANDBOX_RUNTIME_IMAGE_DIGEST": "runtime@sha256:" + "1" * 64,
        "SANDBOX_PACKAGE_MANIFEST_HASH": "2" * 64,
    }


def test_production_settings_fail_closed_without_durable_trust_configuration() -> None:
    with pytest.raises(ValidationError, match="SANDBOX_DEMO_MODE"):
        SandboxSettings(_env_file=None, SANDBOX_ENVIRONMENT="production", SANDBOX_DEMO_MODE=True)

    with pytest.raises(ValidationError, match="postgres persistence"):
        SandboxSettings(_env_file=None, SANDBOX_ENVIRONMENT="production", SANDBOX_ENABLED=True)

    values = production_values()
    values["SANDBOX_AI_ENABLED"] = True
    with pytest.raises(ValidationError, match="PROJECT_AI_FACTORY"):
        SandboxSettings(**values)


def test_production_settings_build_signed_gateway_without_connecting_at_import() -> None:
    settings = SandboxSettings(**production_values())
    app = create_app(
        settings=settings,
        repository=InMemorySandboxSessionRepository(),
        object_store=FakeObjectStore(),
    )

    # Assert the externally published contract. Newer FastAPI versions retain
    # included routers as internal wrapper objects instead of flattening routes.
    paths = set(app.openapi()["paths"])
    assert "/internal/v1/gateway/sessions" in paths
    assert app.state.sandbox_actor_context_resolver is not None
    assert app.state.sandbox_settings.persistence_backend == "postgres"


def test_previous_rotation_keys_must_be_configured_as_a_pair() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        SandboxSettings(
            _env_file=None,
            SANDBOX_SERVICE_AUTH_PREVIOUS_KEY="old-key-with-more-than-32-bytes-value",
        )
