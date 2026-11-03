"""Unit tests for configuration loading and validation."""

import pytest
from pydantic import ValidationError

from common.config import Settings


def test_defaults():
    settings = Settings()
    assert settings.app_name == "KubeSentra"
    assert settings.postgres_port == 5432
    assert settings.database_url.startswith("postgresql://")
    assert settings.database_url.endswith("/kubesentra")


def test_env_vars_override_dotenv(monkeypatch):
    monkeypatch.setenv("POSTGRES_PORT", "5599")
    monkeypatch.setenv("POSTGRES_PASSWORD", "sekrit")
    settings = Settings()
    assert settings.postgres_port == 5599
    assert ":5599/" in settings.database_url
    assert "sekrit" in settings.database_url


def test_invalid_port_is_rejected(monkeypatch):
    monkeypatch.setenv("POSTGRES_PORT", "not-a-port")
    with pytest.raises(ValidationError):
        Settings()


def test_unknown_env_vars_are_ignored(monkeypatch):
    """Future-phase variables must not crash current-phase Settings."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    settings = Settings()
    assert settings.app_name == "KubeSentra"
