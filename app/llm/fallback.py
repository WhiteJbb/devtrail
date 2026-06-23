"""Provider chain with automatic fallback.

FallbackChain은 LLMProvider 프로토콜을 구현한다.
providers 목록을 순서대로 시도하고 LLMError 발생 시 다음 provider로 넘어간다.

fallback 조건:
  - HTTP 503 / 429 / timeout / connection error → 즉시 다음 provider
  - JSON parse 실패 → 같은 provider 1회 재시도 → 그래도 실패 시 다음 provider
"""

from __future__ import annotations

import json
import logging
from typing import Sequence

from app.llm.base import LLMError, LLMNotConfiguredError, LLMProvider

logger = logging.getLogger(__name__)


class FallbackChain:
    """providers를 순서대로 시도. 각 실패(LLMError) 시 다음 provider로 fallback."""

    def __init__(self, providers: Sequence[LLMProvider], task_type: str = "") -> None:
        if not providers:
            raise LLMNotConfiguredError("사용 가능한 LLM provider가 없습니다.")
        self._providers = list(providers)
        self.task_type = task_type
        self.name = "chain[" + "→".join(p.name for p in self._providers) + "]"
        self.model = self._providers[0].model

    def complete(self, prompt: str, system: str = "") -> str:
        """순서대로 provider를 시도. LLMError 발생 시 다음 provider로 fallback."""
        last_exc: LLMError | None = None
        for provider in self._providers:
            try:
                result = provider.complete(prompt, system)
                return result
            except LLMError as e:
                logger.warning(
                    "[fallback] %s 실패 (task=%s): %s → 다음 provider로",
                    provider.name, self.task_type, e,
                )
                last_exc = e

        raise LLMError(
            f"모든 LLM provider 실패 (task={self.task_type!r}). "
            f"chain: {self.name}. 마지막 오류: {last_exc}"
        ) from last_exc

    def complete_with_json_retry(self, prompt: str, system: str = "") -> str:
        """JSON 응답이 필요한 작업용 complete.

        파싱 실패 시 같은 provider로 1회 재시도.
        그래도 실패하면 다음 provider로 fallback.
        """
        last_exc: LLMError | None = None
        for provider in self._providers:
            for attempt in range(2):
                try:
                    result = provider.complete(prompt, system)
                    json.loads(result)  # JSON 유효성 검증
                    return result
                except ValueError as e:
                    if attempt == 0:
                        logger.warning(
                            "[json-retry] %s JSON 파싱 실패, 동일 provider 재시도", provider.name
                        )
                        last_exc = LLMError(f"JSON parse 실패: {e}")
                        continue
                    logger.warning(
                        "[json-retry] %s JSON 파싱 2회 실패 → 다음 provider로", provider.name
                    )
                    last_exc = LLMError(f"JSON parse 실패: {e}")
                    break
                except LLMError as e:
                    logger.warning(
                        "[fallback] %s 실패 (task=%s): %s → 다음 provider로",
                        provider.name, self.task_type, e,
                    )
                    last_exc = e
                    break

        raise LLMError(
            f"모든 LLM provider 실패 (task={self.task_type!r}, json_mode). "
            f"chain: {self.name}. 마지막 오류: {last_exc}"
        ) from last_exc
