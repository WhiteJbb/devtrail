"""FallbackChain + Router 단위 테스트.

API 키 없이 fake provider만 사용한다.
"""

from __future__ import annotations

import json

import pytest

from app.config import Settings
from app.llm.base import LLMError, LLMNotConfiguredError
from app.llm.fallback import FallbackChain
from app.llm.router import get_provider_for_task, get_task_type_for_command


# ── Fake providers ────────────────────────────────────────────────────


class FakeOk:
    def __init__(self, name: str, response: str = "ok"):
        self.name = name
        self.model = f"{name}-model"
        self._response = response

    def complete(self, prompt: str, system: str = "") -> str:
        return self._response


class FakeFail:
    def __init__(self, name: str, message: str = "503 Service Unavailable"):
        self.name = name
        self.model = f"{name}-model"
        self._message = message

    def complete(self, prompt: str, system: str = "") -> str:
        raise LLMError(self._message)


class FakeBadJsonOnce:
    """첫 번째 호출은 invalid JSON, 두 번째 호출은 valid JSON."""

    def __init__(self, valid_response: str = '{"ok": true}'):
        self.name = "bad-json-once"
        self.model = "x"
        self._call_count = 0
        self._valid = valid_response

    def complete(self, prompt: str, system: str = "") -> str:
        self._call_count += 1
        if self._call_count == 1:
            return "not-valid-json"
        return self._valid


class FakeAlwaysBadJson:
    name = "always-bad-json"
    model = "x"

    def complete(self, prompt: str, system: str = "") -> str:
        return "definitely-not-json"


# ── FallbackChain 기본 동작 ──────────────────────────────────────────


def test_fallback_chain_uses_first_provider_when_ok():
    chain = FallbackChain([FakeOk("a", "result-a"), FakeOk("b", "result-b")])
    assert chain.complete("hi") == "result-a"


def test_fallback_chain_skips_to_next_on_llm_error():
    chain = FallbackChain([FakeFail("gemini", "503"), FakeOk("openai", "gpt-result")])
    assert chain.complete("hi") == "gpt-result"


def test_fallback_chain_all_providers_fail_raises_llm_error():
    chain = FallbackChain([FakeFail("a"), FakeFail("b"), FakeFail("c")])
    with pytest.raises(LLMError, match="모든 LLM provider 실패"):
        chain.complete("hi")


def test_fallback_chain_error_message_contains_task_type():
    chain = FallbackChain([FakeFail("gemini")], task_type="light")
    with pytest.raises(LLMError, match="light"):
        chain.complete("hi")


def test_fallback_chain_empty_providers_raises_not_configured():
    with pytest.raises(LLMNotConfiguredError):
        FallbackChain([])


def test_fallback_chain_name_contains_provider_order():
    chain = FallbackChain([FakeOk("a"), FakeOk("b"), FakeOk("c")])
    assert "a" in chain.name
    assert "b" in chain.name
    assert "c" in chain.name


def test_fallback_chain_model_is_first_provider_model():
    chain = FallbackChain([FakeOk("gemini", "r"), FakeOk("openai", "r")])
    assert chain.model == "gemini-model"


# ── FallbackChain JSON retry ──────────────────────────────────────────


def test_json_retry_retries_same_provider_on_parse_failure():
    provider = FakeBadJsonOnce('{"ok": true}')
    chain = FallbackChain([provider])
    result = chain.complete_with_json_retry("prompt")
    assert json.loads(result) == {"ok": True}
    assert provider._call_count == 2


def test_json_retry_falls_back_after_two_parse_failures():
    chain = FallbackChain([
        FakeAlwaysBadJson(),
        FakeOk("next", '{"result": "good"}'),
    ])
    result = chain.complete_with_json_retry("prompt")
    assert json.loads(result) == {"result": "good"}


def test_json_retry_all_fail_raises_llm_error():
    chain = FallbackChain([FakeAlwaysBadJson()], task_type="light")
    with pytest.raises(LLMError, match="모든 LLM provider 실패"):
        chain.complete_with_json_retry("prompt")


# ── Gemini 503 fallback 시나리오 ──────────────────────────────────────


def test_gemini_503_fallback_to_openai():
    chain = FallbackChain([
        FakeFail("gemini", "Gemini 503: Service Unavailable"),
        FakeOk("openai_compatible", "gpt-result"),
        FakeOk("ollama", "ollama-result"),
    ], task_type="light")
    assert chain.complete("test") == "gpt-result"


def test_gemini_and_openai_both_fail_fallback_to_ollama():
    chain = FallbackChain([
        FakeFail("gemini", "503"),
        FakeFail("openai_compatible", "429 Too Many Requests"),
        FakeOk("ollama", "ollama-result"),
    ], task_type="light")
    assert chain.complete("test") == "ollama-result"


def test_all_providers_fail_returns_clear_error_message():
    chain = FallbackChain([
        FakeFail("gemini"),
        FakeFail("openai_compatible"),
        FakeFail("ollama"),
    ], task_type="light")
    with pytest.raises(LLMError) as exc_info:
        chain.complete("test")
    msg = str(exc_info.value)
    assert "모든 LLM provider 실패" in msg
    assert "light" in msg
    assert "chain" in msg


# ── Router: task_type별 chain 순서 ───────────────────────────────────


def _settings(**kwargs) -> Settings:
    base = dict(
        OBSIDIAN_VAULT_PATH="", LLM_PROVIDER="", MESSENGER_PROVIDER="",
        GEMINI_API_KEY="fake-gemini",
        OPENAI_API_KEY="fake-openai",
        KIMI_API_KEY="fake-kimi",
        OLLAMA_BASE_URL="http://localhost:11434",
    )
    base.update(kwargs)
    return Settings(**base)


def test_light_task_chain_starts_with_gemini():
    s = _settings()
    chain = get_provider_for_task("light", s)
    assert chain._providers[0].name == "gemini"


def test_writer_task_chain_starts_with_gemini_flash():
    s = _settings()
    chain = get_provider_for_task("writer", s)
    assert chain._providers[0].name == "gemini"


def test_long_writer_task_chain_starts_with_kimi():
    s = _settings()
    chain = get_provider_for_task("long_writer", s)
    assert chain._providers[0].name == "kimi"


def test_polish_task_chain_starts_with_openai():
    s = _settings()
    chain = get_provider_for_task("polish", s)
    assert chain._providers[0].name == "openai_compatible"


def test_writer_task_chain_order_gemini_openai_kimi():
    s = _settings()
    chain = get_provider_for_task("writer", s)
    names = [p.name for p in chain._providers]
    # gemini → openai → kimi (ollama는 writer chain에 없음)
    assert names.index("gemini") < names.index("openai_compatible")
    assert names.index("openai_compatible") < names.index("kimi")


def test_unknown_task_type_defaults_to_writer_chain():
    s = _settings()
    chain_unknown = get_provider_for_task("nonexistent_type", s)
    chain_writer = get_provider_for_task("writer", s)
    names_unknown = [p.name for p in chain_unknown._providers]
    names_writer = [p.name for p in chain_writer._providers]
    assert names_unknown == names_writer


def test_no_providers_configured_raises_not_configured():
    s = Settings(
        OBSIDIAN_VAULT_PATH="", LLM_PROVIDER="", MESSENGER_PROVIDER="",
        GEMINI_API_KEY="",
        OPENAI_API_KEY="",
        KIMI_API_KEY="",
        OLLAMA_BASE_URL="",
    )
    with pytest.raises(LLMNotConfiguredError):
        get_provider_for_task("light", s)


def test_gemini_only_setup_works_for_writer():
    """기존 Gemini 단독 설정이 writer task에서 동작해야 한다."""
    s = _settings(OPENAI_API_KEY="", KIMI_API_KEY="")
    # ollama_base_url은 기본값 있으므로 chain = [gemini, ollama]
    chain = get_provider_for_task("writer", s)
    names = [p.name for p in chain._providers]
    assert "gemini" in names


def test_gemini_only_long_writer_uses_gemini_as_fallback():
    """Kimi 없는 환경에서 long_writer는 Gemini로 폴백."""
    s = _settings(KIMI_API_KEY="", OPENAI_API_KEY="")
    chain = get_provider_for_task("long_writer", s)
    names = [p.name for p in chain._providers]
    assert "gemini" in names


def test_openai_excluded_when_no_api_key():
    """OPENAI_API_KEY 미설정 시 chain에서 제외."""
    s = _settings(OPENAI_API_KEY="")
    chain = get_provider_for_task("polish", s)
    names = [p.name for p in chain._providers]
    assert "openai_compatible" not in names


def test_kimi_excluded_when_no_api_key():
    """KIMI_API_KEY 미설정 시 chain에서 제외."""
    s = _settings(KIMI_API_KEY="")
    chain = get_provider_for_task("long_writer", s)
    names = [p.name for p in chain._providers]
    assert "kimi" not in names


# ── Router: env override (LONG_WRITER_PROVIDER / POLISH_PROVIDER) ─────


def test_long_writer_provider_env_overrides_first_in_chain():
    """LONG_WRITER_PROVIDER=gemini 이면 long_writer chain 첫 번째가 gemini로 바뀐다."""
    s = _settings(LONG_WRITER_PROVIDER="gemini")
    chain = get_provider_for_task("long_writer", s)
    assert chain._providers[0].name == "gemini"


def test_polish_provider_env_overrides_first_in_chain():
    """POLISH_PROVIDER=gemini 이면 polish chain 첫 번째가 gemini로 바뀐다."""
    s = _settings(POLISH_PROVIDER="gemini", OPENAI_API_KEY="fake-openai")
    chain = get_provider_for_task("polish", s)
    assert chain._providers[0].name == "gemini"


def test_long_writer_provider_env_deduplicates_chain():
    """override provider가 기존 chain에 이미 있으면 중복 없이 앞으로 이동한다."""
    s = _settings(LONG_WRITER_PROVIDER="gemini")
    chain = get_provider_for_task("long_writer", s)
    names = [p.name for p in chain._providers]
    assert names.count("gemini") == 1


# ── get_task_type_for_command ─────────────────────────────────────────


def test_command_to_task_type_light():
    assert get_task_type_for_command("distill-today") == "light"
    assert get_task_type_for_command("suggest-knowledge") == "light"
    assert get_task_type_for_command("capture") == "light"


def test_command_to_task_type_writer():
    assert get_task_type_for_command("write-blog") == "writer"
    assert get_task_type_for_command("resume") == "writer"
    assert get_task_type_for_command("portfolio") == "writer"


def test_command_to_task_type_long_writer():
    assert get_task_type_for_command("weekly-distill") == "long_writer"
    assert get_task_type_for_command("summarize-project") == "long_writer"


def test_command_to_task_type_polish():
    assert get_task_type_for_command("revise-blog") == "polish"


def test_unknown_command_defaults_to_writer():
    assert get_task_type_for_command("some-new-command") == "writer"
