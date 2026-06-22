from typer.testing import CliRunner

from app import cli
from app.llm.base import LLMNotConfiguredError
from app.models import BlogPost, TopicSuggestion

runner = CliRunner()


class _FakeBlogAgent:
    """CLI 테스트용 BlogAgent 대역 (legacy list/preview 커맨드용)."""

    def __init__(self, *a, **k):
        pass

    def preview(self, target="latest"):
        return None


class _FakeDistillAgent:
    """CLI 테스트용 DistillAgent 대역 (suggest-topics용)."""

    raise_llm: bool = False
    suggest_result = None

    def __init__(self, *a, **k):
        pass

    def suggest_blog_topics(self):
        if _FakeDistillAgent.raise_llm:
            raise LLMNotConfiguredError("LLM_PROVIDER 미설정")
        return _FakeDistillAgent.suggest_result


def test_suggest_topics_llm_not_configured(monkeypatch):
    _FakeDistillAgent.raise_llm = True
    monkeypatch.setattr(cli, "DistillAgent", _FakeDistillAgent)
    result = runner.invoke(cli.app, ["suggest-topics"])
    assert result.exit_code == 1
    assert "LLM이 연결되어 있지 않습니다" in result.output


def test_suggest_topics_prints(monkeypatch):
    from app.agents.distill_agent import DistillResult
    from app.services.candidate_writer import CandidateSpec, CandidateWriteResult

    _FakeDistillAgent.raise_llm = False
    from pathlib import Path
    spec = CandidateSpec(kind="blog_idea", title="RAG 환경 분리", body="", summary="worklog 근거")
    written = [CandidateWriteResult(spec=spec, path=Path("/tmp/rag.md"), rel_path="60_Candidates/BlogIdeas/rag.md")]
    _FakeDistillAgent.suggest_result = DistillResult(written=written, source_refs=[])

    monkeypatch.setattr(cli, "DistillAgent", _FakeDistillAgent)
    result = runner.invoke(cli.app, ["suggest-topics"])
    assert result.exit_code == 0
    assert "RAG 환경 분리" in result.output


def test_preview_no_drafts(monkeypatch):
    monkeypatch.setattr(cli, "BlogAgent", _FakeBlogAgent)
    result = runner.invoke(cli.app, ["preview", "latest"])
    assert result.exit_code == 0
    assert "저장된 초안이 없습니다" in result.output


def test_ask_requires_llm(monkeypatch):
    # LLM 미설정 환경에서는 자연어 해석이 불가 → 안내 후 exit 1
    from app.llm.base import LLMNotConfiguredError
    from app.llm import factory as llm_factory

    monkeypatch.setattr(
        llm_factory, "get_llm_provider",
        lambda s: (_ for _ in ()).throw(LLMNotConfiguredError("LLM_PROVIDER 미설정"))
    )
    result = runner.invoke(cli.app, ["ask", "오늘 회고 정리해줘"])
    assert result.exit_code == 1
    assert "LLM이 연결되어 있지 않습니다" in result.output
