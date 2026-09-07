from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "LitReview Agent"
    app_env: Literal["development", "production", "test"] = "development"
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    observability_event_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    cors_origins: str = "http://localhost:3000"

    # Research Sandbox. The top-level switch is deliberately off by default so
    # Mindmap, Literature Review and RAG keep their existing behavior unless a
    # user explicitly invokes an enabled Sandbox capability through the BFF.
    sandbox_enabled: bool = False
    sandbox_demo_mode: bool = False
    sandbox_hypothesis_enabled: bool = False
    sandbox_graph_overlay_enabled: bool = False
    sandbox_data_analysis_enabled: bool = False
    sandbox_ai_enabled: bool = False
    sandbox_graph_context_enabled: bool = False
    sandbox_result_interpretation_enabled: bool = False

    # Core-backend BFF connection and bounded proxy behavior.
    sandbox_control_url: str = ""
    sandbox_service_auth_key: str = ""
    sandbox_service_auth_key_id: str = "sandbox-v1"
    sandbox_service_auth_previous_key: str = ""
    sandbox_service_auth_previous_key_id: str = ""
    sandbox_context_signing_key: str = ""
    sandbox_context_signing_key_id: str = "sandbox-context-v1"
    sandbox_context_signing_previous_key: str = ""
    sandbox_context_signing_previous_key_id: str = ""
    sandbox_request_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    # LLM-backed mutations are synchronous at the Control API boundary and can
    # legitimately outlive the short availability timeout used by core reads.
    sandbox_ai_request_timeout_seconds: float = Field(default=180.0, ge=10.0, le=300.0)
    sandbox_proxy_max_request_bytes: int = Field(default=55 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)
    sandbox_proxy_max_response_bytes: int = Field(default=70 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    # Independently deployed Sandbox control/worker persistence and storage.
    # These values are namespaced so they cannot override core database config.
    sandbox_environment: Literal["development", "test", "production"] = "development"
    sandbox_persistence_backend: Literal["memory", "postgres"] = "memory"
    sandbox_database_url: str = ""
    sandbox_database_pool_size: int = Field(default=10, ge=1, le=100)
    sandbox_database_max_overflow: int = Field(default=10, ge=0, le=100)
    sandbox_database_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120.0)
    sandbox_object_storage_backend: Literal["local", "s3"] = "local"
    sandbox_object_storage_bucket: str = ""
    sandbox_object_storage_endpoint: str = ""
    sandbox_object_storage_region: str = "us-east-1"
    sandbox_object_storage_access_key: str = ""
    sandbox_object_storage_secret_key: str = ""
    sandbox_object_storage_server_side_encryption: str = ""
    sandbox_local_storage_path: str = ".sandbox-storage"

    # Runtime identity, adapters and durable worker controls.
    sandbox_manifest_signing_key: str = "sandbox-local-development-signing-key-32b"
    sandbox_project_ai_factory: str = ""
    sandbox_graph_snapshot_reader_factory: str = ""
    sandbox_adoption_bridge_factory: str = ""
    sandbox_runtime_image_digest: str = "sandbox-runtime@sha256:" + "0" * 64
    sandbox_package_manifest_hash: str = "0" * 64
    sandbox_worker_id: str = "sandbox-worker"
    sandbox_worker_poll_seconds: float = Field(default=1.0, gt=0, le=60.0)
    sandbox_worker_lease_seconds: int = Field(default=180, ge=30, le=3600)
    sandbox_runtime_workspace_path: str = ".sandbox-workspaces"
    sandbox_runtime_seccomp_path: str = "sandbox_runtime/seccomp.json"
    sandbox_docker_binary: str = "docker"
    sandbox_max_sessions_per_project: int | None = Field(default=None, ge=1)

    # Job execution. Embedded keeps local development simple; external keeps
    # HTTP serving separate from durable research-job execution.
    worker_mode: Literal["embedded", "external"] = "embedded"
    runtime_role: Literal["api", "worker"] = "api"
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    worker_max_concurrent_jobs: int = Field(default=2, ge=1, le=20)

    # Redis accelerates worker wake-ups and job-status reads. PostgreSQL stays
    # authoritative, so disabling or losing Redis cannot lose a job.
    redis_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_job_stream: str = "litreview:jobs"
    redis_job_consumer_group: str = "litreview-workers"
    redis_stream_block_ms: int = Field(default=1000, ge=100, le=60_000)
    worker_lease_seconds: int = Field(default=45, ge=10, le=300)
    worker_heartbeat_seconds: int = Field(default=10, ge=1, le=60)
    redis_status_ttl_seconds: int = Field(default=30, ge=1, le=3600)
    # Deprecated pilot setting retained for configuration compatibility.
    # Production disables the bootstrap endpoint; local/test may use actor
    # claims directly to keep deterministic integration tests hermetic.
    v2_bootstrap_tokens: str = ""

    # Clerk is the identity source. Development/test may still use the
    # deterministic bootstrap session endpoint so the local test suite remains
    # hermetic. Production requires a verified Clerk bearer token.
    clerk_issuer: str = ""
    clerk_jwks_url: str = ""
    clerk_authorized_parties: str = "http://localhost:3000"
    clerk_webhook_signing_secret: str = ""

    # LLM routing. In auto mode, only fully configured providers are candidates.
    # With an explicit provider, cross-provider fallback is intentionally disabled.
    llm_provider: Literal["openai", "google", "ollama", "opencode", "openrouter", "auto"] = "auto"
    llm_model: str = "gemini-2.5-flash"
    llm_api_key: str = ""

    # Provider-specific primary keys (for auto-detect / backward compatibility)
    openai_api_key: str = ""
    google_api_key: str = ""
    ollama_api_key: str = ""
    opencode_api_key: str = ""
    openrouter_api_key: str = ""

    # Optional comma-separated key pools.  Keys are attempted in order and
    # never logged.  A second key is useful for controlled key rotation.
    openai_api_keys: str = ""

    # Optional generated illustrations for research-slide decks.  This uses the
    # existing server-side OpenAI key and never exposes it to the browser.
    slide_image_generation_enabled: bool = True
    slide_image_model: str = "gpt-image-2"
    slide_image_quality: Literal["low", "medium", "high", "auto"] = "low"
    slide_image_max_per_deck: int = Field(default=5, ge=0, le=9)
    google_api_keys: str = ""
    ollama_api_keys: str = ""
    opencode_api_keys: str = ""
    openrouter_api_keys: str = ""

    # Provider-specific models used only when falling back from the primary.
    # LLM_MODEL remains the primary model to preserve existing deployments.
    openai_model: str = "gpt-4o"
    google_model: str = "gemini-2.5-flash"
    ollama_model: str = "gemma4:31b-cloud"
    opencode_model: str = "deepseek-v4-flash-free"
    openrouter_model: str = "openrouter/auto"
    ollama_host: str = "https://ollama.com"
    opencode_host: str = "https://opencode.ai/zen/v1"
    openrouter_host: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = ""
    openrouter_app_name: str = "LitReview Agent"

    # Auto-selection and failover order. Unknown/incomplete providers are rejected
    # or skipped before a request is made.
    llm_failover_enabled: bool = True
    llm_fallback_order: str = "google,opencode,ollama,openai,openrouter"

    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_batch_size: int = Field(default=8, ge=1, le=20)
    llm_max_retries: int = Field(default=3, ge=0, le=10)
    llm_timeout: float = Field(default=60.0, ge=10.0, le=300.0)

    # Langfuse observability. Credentials remain backend-only.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_tracing_environment: str = "development"

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/litreview"
    # Product data can use a separate PostgreSQL database. When omitted, it
    # shares DATABASE_URL; runtime persistence is PostgreSQL-only.
    product_database_url: str = ""
    invitation_base_url: str = "http://localhost:3000/"

    # Transactional invitation email. The API key stays backend-only. If either
    # required value is omitted, invitations still work through copyable links.
    resend_api_key: str = ""
    resend_from_email: str = ""
    resend_reply_to: str = ""
    resend_timeout_seconds: float = Field(default=10.0, ge=3.0, le=30.0)
    resend_min_interval_seconds: int = Field(default=60, ge=10, le=3600)

    # Academic search — configure credentials only in .env
    academic_request_timeout: float = Field(default=20.0, ge=3.0, le=60.0)
    openalex_email: str = ""
    openalex_api_key: str = ""
    semantic_scholar_api_key: str = ""
    max_ranked_papers: int = Field(default=20, ge=5, le=50)
    academic_openalex_max_retries: int = Field(default=2, ge=0, le=10)
    academic_retry_base_delay_seconds: float = Field(default=2.0, ge=0.0, le=60.0)
    academic_semantic_scholar_min_interval_seconds: float = Field(default=1.1, ge=0.0, le=60.0)
    academic_min_abstract_length: int = Field(default=200, ge=0, le=10_000)
    research_gap_min_corpus_size: int = Field(default=10, ge=1, le=100)
    research_gap_max_corpus_size: int = Field(default=20, ge=1, le=100)
    research_gap_max_queries: int = Field(default=4, ge=1, le=10)
    research_gap_snowball_seed_limit: int = Field(default=5, ge=0, le=20)
    research_gap_snowball_max_results: int = Field(default=10, ge=0, le=50)
    litreview_min_corpus_size: int = Field(default=10, ge=1, le=100)
    litreview_max_search_attempts: int = Field(default=2, ge=1, le=10)
    litreview_embedding_relevance_score: float = Field(default=0.6, ge=0.0, le=1.0)
    litreview_claim_validation_concurrency: int = Field(default=5, ge=1, le=50)
    litreview_fulltext_chunks_per_paper: int = Field(default=4, ge=1, le=20)
    litreview_compose_max_attempts: int = Field(default=2, ge=1, le=10)
    academic_semantic_scholar_max_retries: int = Field(default=2, ge=0, le=10)
    academic_arxiv_max_results: int = Field(default=50, ge=1, le=100)

    # Vector retrieval. Qdrant is a rebuildable derived index; PostgreSQL is
    # the source of truth for jobs, reports, reviews, and evaluations.
    qdrant_enabled: bool = False
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "litreview_papers"
    qdrant_embedding_model: str = "BAAI/bge-small-en-v1.5"
    qdrant_embedding_provider: Literal["gemini", "fastembed"] = "gemini"
    gemini_embedding_model: str = "models/gemini-embedding-001"
    gemini_embedding_dimensions: int = Field(default=3072, ge=1)
    # A local FastEmbed collection is kept separate from Gemini's 3072-dimension
    # collection.  This lets a job fall back safely without recreating (and
    # deleting) vectors written by jobs that are still using Gemini.
    qdrant_fallback_enabled: bool = True
    qdrant_fallback_collection: str = "litreview_papers_fastembed"
    qdrant_fallback_embedding_model: str = "BAAI/bge-small-en-v1.5"
    # A broader lexical pool prevents one focused sub-query from crowding out
    # relevant papers for the other facets of a multi-part research question.
    qdrant_embedding_candidate_limit: int = Field(default=40, ge=5, le=100)
    qdrant_timeout: float = Field(default=20.0, ge=3.0, le=60.0)

    # Downloaded PDFs are a rebuildable cache for the RAG index. Keep them out
    # of the application bind mount by default: that mount can be read-only or
    # owned by another container in deployment.
    paper_storage_dir: str = "/tmp/litreview-papers"

    # Editable source bundles are short-lived working artifacts rather than
    # product records, so they stay in application storage by default.
    document_review_storage_dir: str = ""
    document_review_max_file_size_mb: int = Field(default=20, ge=1, le=100)
    document_review_max_pdf_pages: int = Field(default=60, ge=1, le=500)
    document_review_link_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    document_review_link_check_concurrency: int = Field(default=8, ge=1, le=32)
    document_review_max_sections_critic: int = Field(default=20, ge=1, le=100)
    document_review_critic_concurrency: int = Field(default=4, ge=1, le=16)
    document_review_max_suggestions: int = Field(default=12, ge=1, le=50)
    document_review_max_citations_verify: int = Field(default=50, ge=1, le=150)
    document_review_citation_verify_concurrency: int = Field(default=4, ge=1, le=16)
    document_review_citation_lookup_timeout_seconds: float = Field(default=15.0, ge=3.0, le=60.0)
    document_review_llm_call_timeout_seconds: float = Field(default=30.0, ge=5.0, le=300.0)
    document_review_claim_timeout_seconds: float = Field(default=90.0, ge=5.0, le=120.0)
    document_review_claim_max_pairs: int = Field(default=30, ge=1, le=100)
    document_review_claim_concurrency: int = Field(default=2, ge=1, le=10)
    document_review_claim_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    document_review_critic_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    document_review_explain_temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    document_review_rewrite_temperature: float = Field(default=0.5, ge=0.0, le=2.0)
    # LlamaParse keeps OCR/layout processing out of the API container. Leave
    # the key empty to use the local pypdf fallback without sending files out.
    document_review_llamaparse_api_key: str = ""
    document_review_llamaparse_base_url: str = "https://api.cloud.llamaindex.ai"
    document_review_llamaparse_tier: str = "agentic"
    document_review_llamaparse_timeout_seconds: int = Field(default=90, ge=30, le=900)
    document_review_source_retention_hours: int = Field(default=24, ge=1, le=720)


@lru_cache
def get_settings() -> Settings:
    return Settings()
