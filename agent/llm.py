"""Configurable LLM provider interface (implementation document section 3).

One implementation covers every OpenAI-compatible endpoint (OpenAI,
OpenRouter, DeepSeek, Groq, Ollama) via LLM_BASE_URL; Anthropic is available
natively. Fails with a clear, actionable error when no key is configured -
KubeSentra never simulates LLM responses.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from common.config import get_settings


class LLMNotConfigured(RuntimeError):
    """Raised when the LLM settings are incomplete - never simulate a model."""


EXAMPLES = (
    "  OpenRouter:  LLM_PROVIDER=openai_compatible, "
    "LLM_BASE_URL=https://openrouter.ai/api/v1, LLM_API_KEY=sk-or-..., "
    "LLM_PRIMARY_MODEL=openai/gpt-4o-mini\n"
    "  OpenAI:      LLM_PROVIDER=openai_compatible, LLM_API_KEY=sk-..., "
    "LLM_PRIMARY_MODEL=gpt-4o-mini\n"
    "  Anthropic:   LLM_PROVIDER=anthropic, LLM_API_KEY=sk-ant-..., "
    "LLM_PRIMARY_MODEL=claude-sonnet-4-5\n"
    "  Gemini:      LLM_PROVIDER=google, LLM_API_KEY=AIza..., "
    "LLM_PRIMARY_MODEL=gemini-3-flash-preview  (native client - required "
    "for Gemini 3 thought signatures in tool loops)\n"
    "  Ollama:      LLM_PROVIDER=openai_compatible, "
    "LLM_BASE_URL=http://127.0.0.1:11434/v1, LLM_API_KEY=ollama, "
    "LLM_PRIMARY_MODEL=qwen2.5:7b"
)


def build_llm(role: str = "primary") -> BaseChatModel:
    """Build the configured chat model. role is 'primary' or 'cheap'."""
    settings = get_settings()
    if role not in ("primary", "cheap"):
        raise ValueError(f"unknown LLM role {role!r}")
    model = (settings.llm_primary_model if role == "primary"
             else settings.llm_cheap_model)
    if not model:
        raise LLMNotConfigured(
            f"LLM_{role.upper()}_MODEL is not set. Example .env entries:\n"
            + EXAMPLES
        )

    api_key = settings.llm_api_key
    base_url = settings.llm_base_url or None

    if settings.llm_provider == "anthropic":
        if not api_key:
            raise LLMNotConfigured("LLM_API_KEY is required for provider=anthropic")
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model, api_key=api_key, timeout=120, temperature=0,
        )

    if settings.llm_provider == "google":
        # Native client: Gemini 3 models attach "thought signatures" to
        # function calls which MUST round-trip on multi-turn tool loops.
        # The OpenAI-compat endpoint drops them -> 400 on the second call.
        if not api_key:
            raise LLMNotConfigured("LLM_API_KEY is required for provider=google")
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model, google_api_key=api_key, temperature=0,
        )

    # openai_compatible provider
    if not api_key:
        # a local Ollama endpoint ignores the key but the client requires one
        if base_url and "localhost" in base_url or base_url and "127.0.0.1" in base_url:
            api_key = "local-not-needed"
        else:
            raise LLMNotConfigured(
                "LLM_API_KEY is not set (and LLM_BASE_URL does not point to a "
                "local endpoint). Example .env entries:\n" + EXAMPLES
            )
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model, api_key=api_key, base_url=base_url,
        timeout=120, temperature=0,
    )


def llm_configured() -> bool:
    """True when both a model and credentials are present for the primary role."""
    settings = get_settings()
    if not settings.llm_primary_model:
        return False
    if settings.llm_api_key:
        return True
    base = settings.llm_base_url or ""
    return "localhost" in base or "127.0.0.1" in base
