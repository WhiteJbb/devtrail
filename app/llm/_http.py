"""LLM provider 공용 HTTP 재시도 헬퍼.

일시적 네트워크 오류/5xx는 지수 백오프로 재시도하고, 4xx(클라이언트 오류)는
재시도 의미가 없으므로 즉시 실패한다.
"""

from __future__ import annotations

import time
from typing import Callable

import httpx

from app.llm.base import LLMError


def request_with_retry(
    do_request: Callable[[], httpx.Response],
    attempts: int = 2,
    base_delay: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """do_request()를 호출하고 raise_for_status까지 수행해 응답을 반환.

    실패 시 attempts회까지 재시도(지수 백오프). 4xx는 재시도 없이 LLMError.
    """
    attempts = max(1, attempts)
    last_exc: Exception | None = None

    for i in range(attempts):
        try:
            resp = do_request()
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if 400 <= status < 500:
                raise LLMError(f"LLM 요청 오류({status}): {e}") from e
            last_exc = e  # 5xx 등은 재시도
        except httpx.HTTPError as e:
            last_exc = e  # 연결/타임아웃 등

        if i < attempts - 1:
            sleep(base_delay * (2**i))

    raise LLMError(f"LLM 호출 실패(재시도 {attempts}회): {last_exc}") from last_exc
