"""task_type 기반 LLM provider 라우터.

task_type에 따라 적절한 FallbackChain을 구성해 반환한다.
설정되지 않은 provider는 체인에서 조용히 제외된다.

task_type별 라우팅:
  light:       Gemini Flash-Lite → GPT-4o mini → Ollama
  writer:      Gemini Flash → GPT-4o mini → Kimi
  long_writer: Kimi → Gemini Flash → GPT-4o mini
  polish:      GPT-4o mini → Gemini Flash
  local:       Ollama (emergency only)
"""

from __future__ import annotations

import logging
from typing import Callable

from app.config import Settings
from app.llm.base import LLMNotConfiguredError, LLMProvider
from app.llm.fallback import FallbackChain
from app.llm.gemini_provider import GeminiProvider
from app.llm.kimi_provider import KimiProvider
from app.llm.ollama_provider import OllamaProvider
from app.llm.openai_compatible_provider import OpenAICompatibleProvider

logger = logging.getLogger(__name__)

# task_type → provider 이름 순서 (우선순위 높은 것부터)
TASK_CHAINS: dict[str, list[str]] = {
    "light":       ["gemini_lite", "openai", "ollama"],
    "writer":      ["gemini_flash", "openai", "kimi"],
    "long_writer": ["kimi", "gemini_flash", "openai"],
    "polish":      ["openai", "gemini_flash"],
    "local":       ["ollama"],
}

# CLI 커맨드 → task_type 매핑
COMMAND_TASK_MAP: dict[str, str] = {
    "capture":              "light",
    "distill-today":        "light",
    "suggest-knowledge":    "light",
    "suggest-blog-topics":  "light",
    "suggest-memory-patch": "light",
    "ask":                  "light",
    "write-blog":           "writer",
    "worklog":              "writer",
    "resume":               "writer",
    "portfolio":            "writer",
    "portfolio-draft":      "writer",
    "interview-questions":  "writer",
    "weekly-distill":       "long_writer",
    "summarize-project":    "long_writer",
    "revise-blog":          "polish",
}


def _make_gemini_lite(settings: Settings) -> GeminiProvider | None:
    if not settings.gemini_api_key:
        return None
    return GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_lite_model,
        max_retries=settings.llm_max_retries,
    )


def _make_gemini_flash(settings: Settings) -> GeminiProvider | None:
    if not settings.gemini_api_key:
        return None
    return GeminiProvider(
        api_key=settings.gemini_api_key,
        model=settings.gemini_flash_model,
        max_retries=settings.llm_max_retries,
    )


def _make_openai(settings: Settings) -> OpenAICompatibleProvider | None:
    # API 키가 있어야 fallback chain에 포함. 로컬 서버는 기존 LLM_PROVIDER=openai_compatible 경로 사용.
    if not settings.openai_api_key:
        return None
    return OpenAICompatibleProvider(
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        max_tokens=settings.openai_max_tokens,
        context_window=settings.openai_context_window,
    )


def _make_kimi(settings: Settings) -> KimiProvider | None:
    if not settings.kimi_api_key:
        return None
    return KimiProvider(
        base_url=settings.kimi_base_url,
        model=settings.kimi_model,
        api_key=settings.kimi_api_key,
    )


def _make_ollama(settings: Settings) -> OllamaProvider | None:
    if not settings.ollama_base_url:
        return None
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
    )


_ProviderBuilder = Callable[[Settings], "LLMProvider | None"]

_BUILDER_MAP: dict[str, _ProviderBuilder] = {
    "gemini_lite":  _make_gemini_lite,
    "gemini_flash": _make_gemini_flash,
    "openai":       _make_openai,
    "kimi":         _make_kimi,
    "ollama":       _make_ollama,
}


def _build_chain(provider_names: list[str], settings: Settings, task_type: str) -> FallbackChain:
    providers: list[LLMProvider] = []
    for name in provider_names:
        builder = _BUILDER_MAP.get(name)
        if builder is None:
            continue
        try:
            p = builder(settings)
            if p is not None:
                providers.append(p)
        except Exception as e:
            logger.debug("[router] %s 초기화 실패, chain에서 제외: %s", name, e)

    if not providers:
        raise LLMNotConfiguredError(
            f"task_type={task_type!r}에 대해 사용 가능한 LLM provider가 없습니다. "
            "관련 API 키(.env)를 설정하세요. "
            f"(필요 chain: {' → '.join(provider_names)})"
        )
    return FallbackChain(providers, task_type=task_type)


def get_provider_for_task(task_type: str, settings: Settings) -> FallbackChain:
    """task_type에 맞는 FallbackChain을 반환한다.

    알 수 없는 task_type이면 writer를 기본으로 사용한다.
    """
    chain_names = TASK_CHAINS.get(task_type, TASK_CHAINS["writer"])
    return _build_chain(chain_names, settings, task_type)


def get_task_type_for_command(command: str) -> str:
    """CLI 커맨드 이름 → task_type. 알 수 없으면 'writer'."""
    return COMMAND_TASK_MAP.get(command, "writer")
