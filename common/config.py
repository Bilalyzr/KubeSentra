"""Application configuration.

All settings come from environment variables (optionally via a .env file in
the repository root). Real environment variables take precedence over .env
values. Settings for phases that are not implemented yet (LLM provider,
Langfuse, Kubernetes lab) are documented in .env.example and added here when
the corresponding phase consumes them.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated KubeSentra configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "KubeSentra"
    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # --- Database ---
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "kubesentra"
    postgres_user: str = "kubesentra"
    postgres_password: str = "kubesentra_dev"

    # --- Laboratory endpoints (Phase 2) ---
    prometheus_url: str = "http://127.0.0.1:9090"
    loki_url: str = "http://127.0.0.1:13100"

    # --- Kubernetes access (Phase 3) ---
    app_namespace: str = "boutique"
    protected_namespaces: list[str] = [
        "kube-system", "monitoring", "chaos-mesh", "kubesentra-system",
    ]
    # Dedicated restricted kubeconfig for the k8s-read MCP server; empty
    # string -> fall back to the default kubeconfig (development only).
    k8s_reader_kubeconfig: str = ""

    # --- LLM (Phase 4) ---
    # openai_compatible covers OpenAI, OpenRouter, DeepSeek, Groq, Ollama
    # (via LLM_BASE_URL); "anthropic" and "google" use native clients.
    llm_provider: str = "openai_compatible"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_primary_model: str = ""
    llm_cheap_model: str = ""

    # --- Incidents (Phase 4) ---
    dedupe_window_minutes: int = 10

    # --- Investigation (Phase 5) ---
    # multi_agent = LangGraph Triage/Supervisor/specialists (default);
    # baseline = Phase 4 single ReAct agent (kept for E1 comparison)
    investigation_mode: str = "multi_agent"
    max_investigation_steps: int = 15      # supervisor loop budget (spec 4.3)
    specialist_max_tool_calls: int = 4     # per specialist turn (spec 7.6)
    investigation_timeout_s: int = 1200    # overall wall-clock cap (Gemini
    # free-tier latency + retry backoffs need headroom over the 5-min target)
    llm_retry_attempts: int = 3            # e.g. Gemini free-tier 429s
    llm_retry_backoff_s: int = 20

    # --- Evaluation experiment switches (Phase 9) ---
    # E2: episodic memory at triage; E3: runbook retrieval at planning.
    # Both default ON (production behaviour); eval runs toggle them OFF to
    # measure their contribution.
    memory_enabled: bool = True
    rag_enabled: bool = True

    # --- Remediation & approval (Phase 6) ---
    # Bearer token required by POST /incidents/{id}/decision
    approval_token: str = "kubesentra-dev-approval"
    # action parameter policy (spec section 7)
    scale_min_replicas: int = 1
    scale_max_replicas: int = 5
    set_resources_max_factor: float = 2.0  # never more than 2x current
    k8s_write_kubeconfig: str = ""         # .secrets/k8s-write.kubeconfig
    # local embedding model (bge-small-en-v1.5, 384 dims)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = ".models"   # repo-local, git-ignored

    @property
    def database_url(self) -> str:
        """PostgreSQL connection string for psycopg3."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings instance (cached)."""
    return Settings()
