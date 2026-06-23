"""Gemini provider + LLM router 테스트."""

import pytest

from app.config import Settings
from app.llm.factory import _FallbackProvider, get_llm_provider, get_local_llm_provider, get_writer_llm_provider
from app.llm.base import LLMError, LLMNotConfiguredError
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


def test_local_provider_with_gemini_returns_fallback_wrapper():
    """로컬 + Gemini 모두 설정 → FallbackProvider로 래핑."""
    from app.llm.ollama_provider import OllamaProvider

    s = _settings(
        LOCAL_LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL="http://localhost:11434",
        GEMINI_API_KEY="fake-key",
    )
    provider = get_local_llm_provider(s)
    assert isinstance(provider, _FallbackProvider)
    assert isinstance(provider._primary, OllamaProvider)
    assert isinstance(provider._fallback, GeminiProvider)


def test_local_provider_without_gemini_returns_primary_directly():
    """로컬만 설정, Gemini 없음 → 래퍼 없이 직접 반환."""
    from app.llm.ollama_provider import OllamaProvider

    s = _settings(
        LOCAL_LLM_PROVIDER="ollama",
        OLLAMA_BASE_URL="http://localhost:11434",
        GEMINI_API_KEY="",
    )
    provider = get_local_llm_provider(s)
    assert isinstance(provider, OllamaProvider)


def test_local_provider_not_set_falls_back_to_gemini():
    """LOCAL_LLM_PROVIDER 미설정 + Gemini 있음 → Gemini 반환."""
    s = _settings(
        LOCAL_LLM_PROVIDER="",
        GEMINI_API_KEY="fake-key",
    )
    provider = get_local_llm_provider(s)
    assert isinstance(provider, GeminiProvider)


def test_local_provider_not_set_no_gemini_falls_back_to_llm_provider():
    """LOCAL_LLM_PROVIDER 미설정 + Gemini 없음 → LLM_PROVIDER로 폴백."""
    s = _settings(
        LLM_PROVIDER="gemini",
        GEMINI_API_KEY="fake-key",
        LOCAL_LLM_PROVIDER="",
    )
    provider = get_local_llm_provider(s)
    assert isinstance(provider, GeminiProvider)


def test_fallback_provider_uses_fallback_on_llm_error():
    """primary에서 LLMError 발생 시 fallback.complete()를 호출한다."""

    class _FailProvider:
        name = "fail"
        model = "x"

        def complete(self, prompt: str, system: str = "") -> str:
            raise LLMError("connection refused")

    class _OkProvider:
        name = "ok"
        model = "y"

        def complete(self, prompt: str, system: str = "") -> str:
            return "fallback result"

    p = _FallbackProvider(_FailProvider(), _OkProvider())
    assert p.complete("test") == "fallback result"
