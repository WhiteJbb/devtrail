"""Gemini provider + LLM router 테스트."""

import pytest

from app.config import Settings
from app.llm.factory import get_llm_provider, get_local_llm_provider, get_writer_llm_provider
from app.llm.base import LLMNotConfiguredError
from app.llm.gemini_provider import GeminiProvider


def _settings(**kwargs) -> Settings:
    base = dict(OBSIDIAN_VAULT_PATH="", LLM_PROVIDER="", MESSENGER_PROVIDER="")
    base.update(kwargs)
    return Settings(**base)


# ── GeminiProvider ───────────────────────────────────────────────────


def test_gemini_provider_raises_without_api_key():
    with pytest.raises(LLMNotConfiguredError):
        GeminiProvider(api_key="")


def test_gemini_provider_created_with_key():
    p = GeminiProvider(api_key="fake-key", model="gemini-2.5-flash")
    assert p.name == "gemini"
    assert p.model == "gemini-2.5-flash"


# ── get_llm_provider ────────────────────────────────────────────────


def test_get_llm_provider_gemini(monkeypatch):
    s = _settings(LLM_PROVIDER="gemini", GEMINI_API_KEY="fake-key")
    provider = get_llm_provider(s)
    assert isinstance(provider, GeminiProvider)


def test_get_llm_provider_unknown_raises():
    s = _settings(LLM_PROVIDER="unknown-provider")
    with pytest.raises(LLMNotConfiguredError, match="지원하지 않는"):
        get_llm_provider(s)


def test_get_llm_provider_empty_raises():
    s = _settings(LLM_PROVIDER="")
    with pytest.raises(LLMNotConfiguredError):
        get_llm_provider(s)


# ── get_writer_llm_provider ─────────────────────────────────────────


def test_writer_provider_uses_writer_setting():
    s = _settings(
        LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL="http://localhost:11434",
        WRITER_PROVIDER="gemini",
        GEMINI_API_KEY="fake-key",
    )
    provider = get_writer_llm_provider(s)
    assert isinstance(provider, GeminiProvider)


def test_writer_provider_falls_back_to_llm_provider():
    s = _settings(
        LLM_PROVIDER="gemini",
        GEMINI_API_KEY="fake-key",
        WRITER_PROVIDER="",
    )
    provider = get_writer_llm_provider(s)
    assert isinstance(provider, GeminiProvider)


# ── get_local_llm_provider ──────────────────────────────────────────


def test_local_provider_uses_local_setting():
    s = _settings(
        LLM_PROVIDER="gemini",
        GEMINI_API_KEY="fake-key",
        LOCAL_LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL="http://localhost:11434",
    )
    from app.llm.ollama_provider import OllamaProvider
    provider = get_local_llm_provider(s)
    assert isinstance(provider, OllamaProvider)


def test_local_provider_falls_back_to_llm_provider():
    s = _settings(
        LLM_PROVIDER="gemini",
        GEMINI_API_KEY="fake-key",
        LOCAL_LLM_PROVIDER="",
    )
    provider = get_local_llm_provider(s)
    assert isinstance(provider, GeminiProvider)
