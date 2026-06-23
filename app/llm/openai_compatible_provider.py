"""OpenAI-compatible provider — vLLM / OpenAI / Ollama(/v1) 공통.

`/chat/completions` 엔드포인트를 호출한다. base_url + model + api_key만 바꾸면
여러 백엔드를 동일 코드로 사용할 수 있다.
"""

from __future__ import annotations

import httpx

from app.llm._http import request_with_retry
from app.llm.base import LLMError


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 120.0,
        max_retries: int = 2,
        max_tokens: int = 1024,
        context_window: int = 0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.context_window = context_window  # 0 = 제한 없음

    def _truncate_to_window(self, prompt: str, system: str) -> str:
        """context_window가 설정된 경우 프롬프트를 잘라 토큰 초과를 방지한다."""
        if not self.context_window:
            return prompt
        # 3 chars/token 보수적 추정. system + 여유분(200토큰) + max_tokens 제외.
        overhead_chars = (len(system) + (200 + self.max_tokens) * 3)
        char_limit = self.context_window * 3 - overhead_chars
        if len(prompt) > char_limit > 0:
            prompt = prompt[:char_limit].rstrip() + "\n...(컨텍스트 초과로 생략)"
        return prompt

    def complete(self, prompt: str, system: str = "") -> str:
        prompt = self._truncate_to_window(prompt, system)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {"model": self.model, "messages": messages, "temperature": 0.4, "max_tokens": self.max_tokens}

        resp = request_with_retry(
            lambda: httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            ),
            attempts=self.max_retries,
        )
        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, ValueError) as e:
            raise LLMError(f"OpenAI-compatible 응답 형식 오류: {e}") from e
