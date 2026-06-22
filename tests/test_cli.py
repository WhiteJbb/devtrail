from typer.testing import CliRunner

from app import cli
from app.llm.base import LLMNotConfiguredError
from app.models import BlogPost, TopicSuggestion

runner = CliRunner()


class _FakeAgent:
    """CLI 테스트용 BlogAgent 대역."""

    suggest_result: list = []
    raise_llm: bool = False

    def __init__(self, *a, **k):
        pass

    def suggest_topics(self):
        if _FakeAgent.raise_llm:
            raise LLMNotConfiguredError("LLM_PROVIDER 미설정")
        return _FakeAgent.suggest_result

    def preview(self, target="latest"):
        return None


def test_suggest_topics_llm_not_configured(monkeypatch):
    _FakeAgent.raise_llm = True
    monkeypatch.setattr(cli, "BlogAgent", _FakeAgent)
    result = runner.invoke(cli.app, ["suggest-topics"])
    assert result.exit_code == 1
    assert "LLM이 연결되어 있지 않습니다" in result.output


def test_suggest_topics_prints(monkeypatch):
    _FakeAgent.raise_llm = False
    _FakeAgent.suggest_result = [
        TopicSuggestion(
            title_candidates=["RAG 환경 분리"],
            reason="worklog 근거",
            outline=["문제", "해결"],
            source_refs=["worklog:worklog"],
        )
    ]
    monkeypatch.setattr(cli, "BlogAgent", _FakeAgent)
    result = runner.invoke(cli.app, ["suggest-topics"])
    assert result.exit_code == 0
    assert "RAG 환경 분리" in result.output
    assert "worklog:worklog" in result.output


def test_preview_no_drafts(monkeypatch):
    monkeypatch.setattr(cli, "BlogAgent", _FakeAgent)
    result = runner.invoke(cli.app, ["preview", "latest"])
    assert result.exit_code == 0
    assert "저장된 초안이 없습니다" in result.output


def test_ask_requires_llm():
    # LLM 미설정 환경에서는 자연어 해석이 불가 → 안내 후 exit 1
    result = runner.invoke(cli.app, ["ask", "오늘 회고 정리해줘"])
    assert result.exit_code == 1
    assert "LLM이 연결되어 있지 않습니다" in result.output
