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
