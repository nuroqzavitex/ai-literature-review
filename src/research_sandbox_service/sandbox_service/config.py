"""Configuration for the independently deployable sandbox service."""

from pathlib import Path
import re
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SandboxSettings(BaseSettings):
    """Settings kept separate from the main backend configuration."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="SANDBOX_ENVIRONMENT"
    )
    enabled: bool = Field(default=False, validation_alias="SANDBOX_ENABLED")
    demo_mode: bool = Field(default=False, validation_alias="SANDBOX_DEMO_MODE")
    hypothesis_enabled: bool = Field(default=False, validation_alias="SANDBOX_HYPOTHESIS_ENABLED")
    graph_overlay_enabled: bool = Field(default=False, validation_alias="SANDBOX_GRAPH_OVERLAY_ENABLED")
    data_analysis_enabled: bool = Field(default=False, validation_alias="SANDBOX_DATA_ANALYSIS_ENABLED")
    ai_enabled: bool = Field(default=False, validation_alias="SANDBOX_AI_ENABLED")
    allow_local_actor_headers: bool = Field(
        default=False, validation_alias="SANDBOX_ALLOW_LOCAL_ACTOR_HEADERS"
    )
    graph_context_enabled: bool = Field(default=False, validation_alias="SANDBOX_GRAPH_CONTEXT_ENABLED")
    result_interpretation_enabled: bool = Field(default=False, validation_alias="SANDBOX_RESULT_INTERPRETATION_ENABLED")
    database_url: PostgresDsn | None = Field(
        default=None, validation_alias="SANDBOX_DATABASE_URL"
    )
    persistence_backend: Literal["memory", "postgres"] = Field(
        default="memory", validation_alias="SANDBOX_PERSISTENCE_BACKEND"
    )
    database_pool_size: int = Field(
        default=10, ge=1, le=100, validation_alias="SANDBOX_DATABASE_POOL_SIZE"
    )
    database_max_overflow: int = Field(
        default=10, ge=0, le=100, validation_alias="SANDBOX_DATABASE_MAX_OVERFLOW"
    )
    database_pool_timeout_seconds: float = Field(
        default=10.0, gt=0, le=120, validation_alias="SANDBOX_DATABASE_POOL_TIMEOUT_SECONDS"
    )
    object_storage_backend: Literal["local", "s3"] = Field(
        default="local", validation_alias="SANDBOX_OBJECT_STORAGE_BACKEND"
    )
    object_storage_bucket: str | None = Field(
        default=None, validation_alias="SANDBOX_OBJECT_STORAGE_BUCKET"
    )
    object_storage_endpoint: str | None = Field(
        default=None, validation_alias="SANDBOX_OBJECT_STORAGE_ENDPOINT"
    )
    object_storage_region: str = Field(
        default="us-east-1", validation_alias="SANDBOX_OBJECT_STORAGE_REGION"
    )
    object_storage_access_key: SecretStr | None = Field(
        default=None, validation_alias="SANDBOX_OBJECT_STORAGE_ACCESS_KEY"
    )
    object_storage_secret_key: SecretStr | None = Field(
        default=None, validation_alias="SANDBOX_OBJECT_STORAGE_SECRET_KEY"
    )
    object_storage_server_side_encryption: str | None = Field(
        default=None, validation_alias="SANDBOX_OBJECT_STORAGE_SERVER_SIDE_ENCRYPTION"
    )
    local_storage_path: Path = Field(
        default=Path(".sandbox-storage"), validation_alias="SANDBOX_LOCAL_STORAGE_PATH"
    )
    manifest_signing_key: SecretStr = Field(
        default=SecretStr("sandbox-local-development-signing-key-32b"),
        validation_alias="SANDBOX_MANIFEST_SIGNING_KEY",
    )
    service_auth_key: SecretStr | None = Field(
        default=None, validation_alias="SANDBOX_SERVICE_AUTH_KEY"
    )
    service_auth_key_id: str = Field(
        default="sandbox-v1", validation_alias="SANDBOX_SERVICE_AUTH_KEY_ID"
    )
    service_auth_previous_key: SecretStr | None = Field(
        default=None, validation_alias="SANDBOX_SERVICE_AUTH_PREVIOUS_KEY"
    )
    service_auth_previous_key_id: str | None = Field(
        default=None, validation_alias="SANDBOX_SERVICE_AUTH_PREVIOUS_KEY_ID"
    )
    context_signing_key: SecretStr | None = Field(
        default=None, validation_alias="SANDBOX_CONTEXT_SIGNING_KEY"
    )
    context_signing_key_id: str = Field(
        default="sandbox-context-v1", validation_alias="SANDBOX_CONTEXT_SIGNING_KEY_ID"
    )
    context_signing_previous_key: SecretStr | None = Field(
        default=None, validation_alias="SANDBOX_CONTEXT_SIGNING_PREVIOUS_KEY"
    )
    context_signing_previous_key_id: str | None = Field(
        default=None, validation_alias="SANDBOX_CONTEXT_SIGNING_PREVIOUS_KEY_ID"
    )
    project_ai_factory: str | None = Field(
        default=None, validation_alias="SANDBOX_PROJECT_AI_FACTORY"
    )
    graph_snapshot_reader_factory: str | None = Field(
        default=None, validation_alias="SANDBOX_GRAPH_SNAPSHOT_READER_FACTORY"
    )
    adoption_bridge_factory: str | None = Field(
        default=None, validation_alias="SANDBOX_ADOPTION_BRIDGE_FACTORY"
    )
    core_backend_url: str | None = Field(
        default=None, validation_alias="SANDBOX_CORE_BACKEND_URL"
    )
    core_backend_timeout_seconds: float = Field(
        default=10.0,
        ge=0.5,
        le=60.0,
        validation_alias="SANDBOX_CORE_BACKEND_TIMEOUT_SECONDS",
    )
    runtime_image_digest: str = Field(
        default="sandbox-runtime@sha256:" + "0" * 64,
        validation_alias="SANDBOX_RUNTIME_IMAGE_DIGEST",
    )
    runtime_image_name: str = Field(
        default="sandbox_runtime:latest",
        validation_alias="SANDBOX_RUNTIME_IMAGE_NAME",
        pattern=r"^[a-z0-9][a-z0-9._/-]*(?::[a-z0-9._-]+)?$",
    )
    runtime_launcher: Literal["auto", "docker", "native"] = Field(
        default="auto", validation_alias="SANDBOX_RUNTIME_LAUNCHER"
    )
    runtime_python: str = Field(
        default="python3", validation_alias="SANDBOX_RUNTIME_PYTHON"
    )
    runtime_sdk_path: Path = Field(
        default=Path("sandbox_runtime/sandbox_sdk"),
        validation_alias="SANDBOX_RUNTIME_SDK_PATH",
    )
    bwrap_binary: str = Field(
        default="bwrap", validation_alias="SANDBOX_BWRAP_BINARY"
    )
    package_manifest_hash: str = Field(
        default="0" * 64, validation_alias="SANDBOX_PACKAGE_MANIFEST_HASH"
    )
    worker_id: str = Field(default="sandbox-worker", validation_alias="SANDBOX_WORKER_ID")
    worker_poll_seconds: float = Field(
        default=1.0, gt=0, le=60, validation_alias="SANDBOX_WORKER_POLL_SECONDS"
    )
    worker_lease_seconds: int = Field(
        default=180, ge=30, le=3600, validation_alias="SANDBOX_WORKER_LEASE_SECONDS"
    )
    runtime_workspace_path: Path = Field(
        default=Path(".sandbox-workspaces"),
        validation_alias="SANDBOX_RUNTIME_WORKSPACE_PATH",
    )
    runtime_data_volume_name: str = Field(
        default="research_sandbox_data",
        validation_alias="SANDBOX_DATA_VOLUME_NAME",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,254}$",
    )
    runtime_seccomp_path: Path = Field(
        default=Path("sandbox_runtime/seccomp.json"),
        validation_alias="SANDBOX_RUNTIME_SECCOMP_PATH",
    )
    docker_binary: str = Field(default="docker", validation_alias="SANDBOX_DOCKER_BINARY")
    max_sessions_per_project: int | None = Field(
        default=None, validation_alias="SANDBOX_MAX_SESSIONS_PER_PROJECT", ge=1
    )

    @field_validator("object_storage_bucket")
    @classmethod
    def non_blank_bucket(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("SANDBOX_OBJECT_STORAGE_BUCKET cannot be blank")
        return value

    @field_validator("runtime_python", "bwrap_binary")
    @classmethod
    def non_blank_runtime_command(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("native runtime commands cannot be blank")
        return value.strip()

    @field_validator(
        "service_auth_key",
        "service_auth_previous_key",
        "service_auth_previous_key_id",
        "context_signing_key",
        "context_signing_previous_key",
        "context_signing_previous_key_id",
        "project_ai_factory",
        "graph_snapshot_reader_factory",
        "adoption_bridge_factory",
        "core_backend_url",
        mode="before",
    )
    @classmethod
    def blank_optional_value_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_deployment_contract(self) -> "SandboxSettings":
        if self.environment == "production" and self.demo_mode:
            raise ValueError("production Sandbox cannot enable SANDBOX_DEMO_MODE")
        if self.persistence_backend == "postgres" and self.database_url is None:
            raise ValueError("SANDBOX_DATABASE_URL is required for postgres persistence")
        if self.object_storage_backend == "s3" and not self.object_storage_bucket:
            raise ValueError("SANDBOX_OBJECT_STORAGE_BUCKET is required for S3 storage")
        if self.enabled and self.result_interpretation_enabled and not self.ai_enabled:
            raise ValueError("result interpretation requires SANDBOX_AI_ENABLED=true")
        if bool(self.service_auth_previous_key) != bool(self.service_auth_previous_key_id):
            raise ValueError("previous service-auth key and key id must be configured together")
        if bool(self.context_signing_previous_key) != bool(self.context_signing_previous_key_id):
            raise ValueError("previous context-signing key and key id must be configured together")
        if self.environment == "production" and self.enabled:
            if self.allow_local_actor_headers:
                raise ValueError("production Sandbox cannot trust local actor headers")
            if self.persistence_backend != "postgres":
                raise ValueError("production Sandbox requires postgres persistence")
            if self.object_storage_backend != "s3":
                raise ValueError("production Sandbox requires shared S3-compatible object storage")
            for name, secret in (
                ("SANDBOX_SERVICE_AUTH_KEY", self.service_auth_key),
                ("SANDBOX_CONTEXT_SIGNING_KEY", self.context_signing_key),
            ):
                if secret is None or len(secret.get_secret_value().encode("utf-8")) < 32:
                    raise ValueError(f"production Sandbox requires {name} with at least 32 bytes")
                if secret.get_secret_value().startswith("sandbox-local-"):
                    raise ValueError(f"production Sandbox cannot use a development {name}")
            if self.ai_enabled and not self.project_ai_factory:
                raise ValueError("production AI requires SANDBOX_PROJECT_AI_FACTORY")
            if self.graph_overlay_enabled and not self.graph_snapshot_reader_factory:
                raise ValueError(
                    "production graph-overlay mode requires SANDBOX_GRAPH_SNAPSHOT_READER_FACTORY"
                )
            signing_key = self.manifest_signing_key.get_secret_value()
            if len(signing_key.encode("utf-8")) < 32 or signing_key.startswith("sandbox-local-"):
                raise ValueError("production Sandbox requires a non-development manifest signing key")
            # Docker's local image ID is written by sandbox-runtime-prepare as
            # sha256:<64 hex chars>. Registry references use
            # repository@sha256:<64 hex chars>. Both are immutable; the
            # former is the correct value for a locally built EC2 runtime.
            if not re.fullmatch(r"(?:[^@]+@)?sha256:[0-9a-f]{64}", self.runtime_image_digest):
                raise ValueError("SANDBOX_RUNTIME_IMAGE_DIGEST must be an immutable sha256 digest")
            if self.runtime_image_digest.endswith("0" * 64):
                raise ValueError("production runtime image digest cannot be the development placeholder")
            if not re.fullmatch(r"[0-9a-f]{64}", self.package_manifest_hash) or self.package_manifest_hash == "0" * 64:
                raise ValueError("production package manifest hash must be a real sha256 value")
        return self

    def allows_mode(self, mode: str) -> bool:
        """The top-level kill switch always wins over capability flags."""
        if not self.enabled:
            return False
        return {
            "hypothesis": self.hypothesis_enabled,
            "graph_overlay": self.graph_overlay_enabled,
            "data_analysis": self.data_analysis_enabled,
        }.get(mode, False)
