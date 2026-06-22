"""Ollama 네이티브 provider — /api/generate.

Ollama의 OpenAI-compatible(/v1) 대신 네이티브 엔드포인트를 직접 쓴다.
api_key가 필요 없고 로컬 모델명을 그대로 사용한다.
"""

from __future__ import annotations

import httpx

from app.llm._http import request_with_retry
from app.llm.base import LLMError


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 120.0, max_retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def complete(self, prompt: str, system: str = "") -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": 0.4},
        }
        resp = request_with_retry(
            lambda: httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            ),
            attempts=self.max_retries,
        )
        try:
            data = resp.json()
            return (data.get("response") or "").strip()
        except ValueError as e:
            raise LLMError(f"Ollama 응답 형식 오류: {e}") from e
