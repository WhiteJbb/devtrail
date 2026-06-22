"""Gemini REST API provider.

google-generativeai 패키지 없이 httpx로 직접 Gemini generateContent 엔드포인트를 호출한다.
"""

from __future__ import annotations

import time

import httpx

from app.llm.base import LLMError, LLMNotConfiguredError

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        timeout: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        if not api_key:
            raise LLMNotConfiguredError("GEMINI_API_KEY가 비어 있습니다.")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def complete(self, prompt: str, system: str = "") -> str:
        contents: list[dict] = []
        if system:
            contents.append({"role": "user", "parts": [{"text": system}]})
            contents.append({"role": "model", "parts": [{"text": "알겠습니다."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        url = f"{_BASE_URL}/{self.model}:generateContent"
        payload = {"contents": contents}
        params = {"key": self.api_key}

        last_exc: Exception | None = None
        for attempt in range(max(1, self.max_retries)):
            try:
                resp = httpx.post(url, json=payload, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    return self._extract_text(resp.json())
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_exc = LLMError(f"Gemini {resp.status_code}: {resp.text[:200]}")
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"Gemini API 오류 {resp.status_code}: {resp.text[:200]}")
            except httpx.TimeoutException as e:
                last_exc = LLMError(f"Gemini timeout: {e}")
                time.sleep(2 ** attempt)
            except LLMError:
                raise
            except Exception as e:
                raise LLMError(f"Gemini 호출 실패: {e}") from e

        raise last_exc or LLMError("Gemini 호출 실패: 최대 재시도 초과")

    def _extract_text(self, data: dict) -> str:
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError(f"Gemini 응답 파싱 실패: {e}\n응답: {str(data)[:300]}") from e
