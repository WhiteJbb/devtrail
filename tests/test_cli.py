from typer.testing import CliRunner

from app import cli
from app.llm.base import LLMNotConfiguredError

runner = CliRunner()


class _FakeDistillAgent:
    """CLI 테스트용 DistillAgent 대역 (suggest-blog-topics용)."""

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
    result = runner.invoke(cli.app, ["suggest-blog-topics"])
    assert result.exit_code == 1
    assert "LLM이 연결되어 있지 않습니다" in result.output


def test_suggest_topics_prints(monkeypatch):
    from app.agents.distill_agent import DistillResult
    from app.services.candidate_writer import CandidateSpec, CandidateWriteResult
    from pathlib import Path

    _FakeDistillAgent.raise_llm = False
    spec = CandidateSpec(kind="blog_idea", title="RAG 환경 분리", body="", summary="worklog 근거")
    written = [CandidateWriteResult(spec=spec, path=Path("/tmp/rag.md"), rel_path="60_Candidates/BlogIdeas/rag.md")]
    _FakeDistillAgent.suggest_result = DistillResult(written=written, source_refs=[])

    monkeypatch.setattr(cli, "DistillAgent", _FakeDistillAgent)
    result = runner.invoke(cli.app, ["suggest-blog-topics"])
    assert result.exit_code == 0
    assert "RAG 환경 분리" in result.output


def test_ask_requires_llm(monkeypatch):
    from app.llm import factory as llm_factory

    monkeypatch.setattr(
        llm_factory, "get_llm_provider",
        lambda s: (_ for _ in ()).throw(LLMNotConfiguredError("LLM_PROVIDER 미설정"))
    )
    result = runner.invoke(cli.app, ["ask", "오늘 회고 정리해줘"])
    assert result.exit_code == 1
    assert "LLM이 연결되어 있지 않습니다" in result.output


# ── 후보 검토 CLI (번호 선택 · review) ───────────────────────────────────────


def _tmp_curator(tmp_path):
    from types import SimpleNamespace

    from app.agents.curator_agent import CuratorAgent

    settings = SimpleNamespace(obsidian_vault_root=str(tmp_path))
    return CuratorAgent(settings=settings)


def _write_knowledge_candidate(tmp_path, title="테스트 지식"):
    from app import vault_tools
    from types import SimpleNamespace

    settings = SimpleNamespace(obsidian_vault_root=str(tmp_path))
    return vault_tools.record_note("knowledge", title, "본문", settings=settings)


def test_list_candidates_shows_numbers(tmp_path, monkeypatch):
    _write_knowledge_candidate(tmp_path, title="번호로 고를 지식")
    monkeypatch.setattr(cli, "_curator_agent", lambda: _tmp_curator(tmp_path))
    monkeypatch.setattr(cli, "_pipeline_health_line", lambda: "")

    result = runner.invoke(cli.app, ["list-candidates"])
    assert result.exit_code == 0
    assert "1. [knowledge] 번호로 고를 지식" in result.output


def test_list_candidates_empty_shows_pipeline_health(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_curator_agent", lambda: _tmp_curator(tmp_path))
    monkeypatch.setattr(cli, "_pipeline_health_line", lambda: "⚠ nightly-distill이 4일째 실행되지 않았어요")

    result = runner.invoke(cli.app, ["list-candidates"])
    assert result.exit_code == 0
    assert "후보가 없습니다" in result.output
    assert "nightly-distill" in result.output


def test_promote_candidate_accepts_number(tmp_path, monkeypatch):
    _write_knowledge_candidate(tmp_path, title="승격할 지식")
    monkeypatch.setattr(cli, "_curator_agent", lambda: _tmp_curator(tmp_path))

    result = runner.invoke(cli.app, ["promote-candidate", "1"])
    assert result.exit_code == 0
    assert "승격 완료" in result.output
    assert (tmp_path / "20_Knowledge").exists()


def test_promote_candidate_rejects_out_of_range_number(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_curator_agent", lambda: _tmp_curator(tmp_path))

    result = runner.invoke(cli.app, ["promote-candidate", "3"])
    assert result.exit_code == 1
    assert "해당하는 후보가 없습니다" in result.output


def test_review_promotes_and_skips(tmp_path, monkeypatch):
    _write_knowledge_candidate(tmp_path, title="검토 1번")
    _write_knowledge_candidate(tmp_path, title="검토 2번")
    monkeypatch.setattr(cli, "_curator_agent", lambda: _tmp_curator(tmp_path))
    monkeypatch.setattr(cli, "_pipeline_health_line", lambda: "")

    result = runner.invoke(cli.app, ["review"], input="p\ns\n")
    assert result.exit_code == 0
    assert "승격" in result.output
    assert "처리 1건" in result.output


def test_review_quit_early(tmp_path, monkeypatch):
    _write_knowledge_candidate(tmp_path, title="검토 지식")
    monkeypatch.setattr(cli, "_curator_agent", lambda: _tmp_curator(tmp_path))
    monkeypatch.setattr(cli, "_pipeline_health_line", lambda: "")

    result = runner.invoke(cli.app, ["review"], input="q\n")
    assert result.exit_code == 0
    assert "검토를 종료합니다" in result.output
