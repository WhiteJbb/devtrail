import pytest

from app.config import Settings
from app.llm import LLMNotConfiguredError, get_llm_provider
from app.llm.ollama_provider import OllamaProvider
from app.llm.openai_compatible_provider import OpenAICompatibleProvider


def test_unset_provider_raises():
    with pytest.raises(LLMNotConfiguredError):
        get_llm_provider(Settings(LLM_PROVIDER=""))


def test_unsupported_provider_raises():
    with pytest.raises(LLMNotConfiguredError):
        get_llm_provider(Settings(LLM_PROVIDER="gpt9000"))


def test_openai_compatible_selected():
    p = get_llm_provider(Settings(LLM_PROVIDER="openai_compatible", OPENAI_MODEL="m"))
    assert isinstance(p, OpenAICompatibleProvider)
    assert p.model == "m"


def test_ollama_selected():
    p = get_llm_provider(Settings(LLM_PROVIDER="ollama", OLLAMA_MODEL="qwen"))
    assert isinstance(p, OllamaProvider)
    assert p.model == "qwen"
