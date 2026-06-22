"""설정 기반 LLM provider 선택."""

from __future__ import annotations

from app.config import Settings
from app.llm.base import LLMNotConfiguredError, LLMProvider
from app.llm.ollama_provider import OllamaProvider
from app.llm.openai_compatible_provider import OpenAICompatibleProvider


def get_llm_provider(settings: Settings) -> LLMProvider:
    """LLM_PROVIDER 설정으로 provider를 만든다.

    미설정/미지원이면 LLMNotConfiguredError. 상위 계층(CLI)은 이를 잡아
    "LLM이 연결되어 있지 않다"고 안내한다(가짜 생성 금지).
    """
    provider = (settings.llm_provider or "").strip().lower()

    if not provider:
        raise LLMNotConfiguredError(
            "LLM provider가 설정되지 않았습니다. .env의 LLM_PROVIDER를 "
            "'openai_compatible' 또는 'ollama'로 지정하세요."
        )

    if provider == "openai_compatible":
        if not settings.openai_base_url:
            raise LLMNotConfiguredError("OPENAI_BASE_URL이 비어 있습니다.")
        return OpenAICompatibleProvider(
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
        )

    if provider == "ollama":
        if not settings.ollama_base_url:
            raise LLMNotConfiguredError("OLLAMA_BASE_URL이 비어 있습니다.")
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
        )

    raise LLMNotConfiguredError(
        f"지원하지 않는 LLM_PROVIDER: {provider!r}. "
        "'openai_compatible' 또는 'ollama' 중 하나여야 합니다."
    )
