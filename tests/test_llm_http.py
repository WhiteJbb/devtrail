import httpx
import pytest

from app.llm._http import request_with_retry
from app.llm.base import LLMError


class FakeResp:
    def __init__(self, status=200):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err",
                request=httpx.Request("POST", "http://x"),
                response=httpx.Response(self.status_code, request=httpx.Request("POST", "http://x")),
            )


def test_retries_transient_then_succeeds():
    calls = {"n": 0}

    def do_request():
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return FakeResp(200)

    resp = request_with_retry(do_request, attempts=3, sleep=lambda _: None)
    assert resp.status_code == 200
    assert calls["n"] == 2


def test_4xx_not_retried():
    calls = {"n": 0}

    def do_request():
        calls["n"] += 1
        return FakeResp(404)

    with pytest.raises(LLMError):
        request_with_retry(do_request, attempts=3, sleep=lambda _: None)
    assert calls["n"] == 1  # 4xx는 재시도 안 함


def test_exhausts_attempts():
    calls = {"n": 0}

    def do_request():
        calls["n"] += 1
        raise httpx.ConnectError("down")

    with pytest.raises(LLMError):
        request_with_retry(do_request, attempts=2, sleep=lambda _: None)
    assert calls["n"] == 2
