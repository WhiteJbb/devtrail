"""설정 기반 LLM provider 선택."""

from __future__ import annotations

from app.config import Settings
from app.llm.base import LLMNotConfiguredError, LLMProvider
from app.llm.gemini_provider import GeminiProvider
from app.llm.ollama_provider import OllamaProvider
from app.llm.openai_compatible_provider import OpenAICompatibleProvider


def get_llm_provider(settings: Settings) -> LLMProvider:
    """LLM_PROVIDER 설정으로 provider를 만든다.

    미설정/미지원이면 LLMNotConfiguredError. 상위 계층(CLI)은 이를 잡아
    "LLM이 연결되어 있지 않다"고 안내한다(가짜 생성 금지).
    """
    return _make_provider(settings.llm_provider, settings)


def get_writer_llm_provider(settings: Settings) -> LLMProvider:
    """글쓰기 작업(write-blog, portfolio, resume 등)용 provider.

    WRITER_PROVIDER가 설정되면 그것을 우선 사용한다.
    미설정이면 LLM_PROVIDER로 폴백한다.
    """
    writer = (settings.writer_provider or "").strip().lower()
    if writer:
        return _make_provider(writer, settings, prefer_flash=True)
    return get_llm_provider(settings)


def get_local_llm_provider(settings: Settings) -> LLMProvider:
    """분류·태깅·짧은 요약 등 저비용 작업용 provider.

    LOCAL_LLM_PROVIDER가 설정되면 그것을 우선 사용한다.
    미설정이면 LLM_PROVIDER로 폴백한다.
    """
    local = (settings.local_llm_provider or "").strip().lower()
    if local:
        return _make_provider(local, settings)
    return get_llm_provider(settings)


def _make_provider(provider_name: str, settings: Settings, prefer_flash: bool = False) -> LLMProvider:
    provider = (provider_name or "").strip().lower()

    if not provider:
        raise LLMNotConfiguredError(
            "LLM provider가 설정되지 않았습니다. .env의 LLM_PROVIDER를 "
            "'openai_compatible', 'ollama', 또는 'gemini'로 지정하세요."
        )

    if provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMNotConfiguredError(
                "GEMINI_API_KEY가 비어 있습니다. .env에서 설정하세요."
            )
        model = settings.gemini_flash_model
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=model,
            max_retries=settings.llm_max_retries,
        )

    if provider == "openai_compatible":
        if not settings.openai_base_url:
            raise LLMNotConfiguredError("OPENAI_BASE_URL이 비어 있습니다.")
        return OpenAICompatibleProvider(
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            max_retries=settings.llm_max_retries,
        )

    if provider == "ollama":
        if not settings.ollama_base_url:
            raise LLMNotConfiguredError("OLLAMA_BASE_URL이 비어 있습니다.")
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    raise LLMNotConfiguredError(
        f"지원하지 않는 LLM provider: {provider!r}. "
        "'openai_compatible', 'ollama', 'gemini' 중 하나여야 합니다."
    )
