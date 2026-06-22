"""OpenAI-compatible provider — vLLM / OpenAI / Ollama(/v1) 공통.

`/chat/completions` 엔드포인트를 호출한다. base_url + model + api_key만 바꾸면
여러 백엔드를 동일 코드로 사용할 수 있다.
"""

from __future__ import annotations

import httpx

from app.llm.base import LLMError


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {"model": self.model, "messages": messages, "temperature": 0.4}

        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except httpx.HTTPError as e:
            raise LLMError(f"OpenAI-compatible 호출 실패: {e}") from e
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"OpenAI-compatible 응답 형식 오류: {e}") from e
