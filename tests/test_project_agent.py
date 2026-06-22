"""ProjectAgent + WikiService.related_notes + revise-blog/publish-ready 테스트."""

from pathlib import Path
from types import SimpleNamespace

import frontmatter
import pytest
from typer.testing import CliRunner

from app import cli
from app.agents.project_agent import ProjectAgent
from app.agents.wiki_blog_agent import WikiBlogAgent
from app.config import Settings
from app.services.wiki_service import WikiService
from tests.conftest import FakeLLM


runner = CliRunner()


def _settings(vault: Path) -> Settings:
    return Settings(OBSIDIAN_VAULT_PATH=str(vault), LLM_PROVIDER="ollama", MESSENGER_PROVIDER="")


def _write_project_context(vault: Path, project: str, body: str) -> None:
    path = vault / "30_Projects" / project / "Context.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, **{"type": "project", "project": project, "status": "active"})
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


def _write_knowledge(vault: Path, rel: str, body: str, tags: list[str] | None = None) -> None:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"type": "knowledge", "tags": tags or []}
    post = frontmatter.Post(body, **meta)
    path.write_text(frontmatter.dumps(post), encoding="utf-8")


# ── WikiService.related_notes ────────────────────────────────────────


def test_related_notes_finds_by_tags(tmp_path):
    _write_knowledge(tmp_path, "20_Knowledge/AI/rag.md", "# RAG\n\nRAG 기초", tags=["rag", "search"])
    _write_knowledge(tmp_path, "20_Knowledge/AI/vector.md", "# Vector\n\n벡터 검색", tags=["rag", "vector"])
    _write_knowledge(tmp_path, "20_Knowledge/Backend/django.md", "# Django\n\nDjango ORM", tags=["django"])

    service = WikiService(tmp_path)
    results = service.related_notes("20_Knowledge/AI/rag.md", limit=5)

    paths = [r.note.path for r in results]
    assert "20_Knowledge/AI/vector.md" in paths
    assert "20_Knowledge/Backend/django.md" not in paths  # 관련 없음


def test_related_notes_excludes_source_note(tmp_path):
    _write_knowledge(tmp_path, "20_Knowledge/AI/rag.md", "# RAG\n\nRAG 기초", tags=["rag"])

    service = WikiService(tmp_path)
    results = service.related_notes("20_Knowledge/AI/rag.md", limit=5)

    paths = [r.note.path for r in results]
    assert "20_Knowledge/AI/rag.md" not in paths


def test_related_notes_returns_empty_for_missing_path(tmp_path):
    service = WikiService(tmp_path)
    results = service.related_notes("20_Knowledge/AI/nonexistent.md")
    assert results == []


# ── WikiBlogAgent.revise_blog ────────────────────────────────────────


def _write_draft(vault: Path, title: str = "RAG 검색 전략") -> str:
    rel = "50_Outputs/Blog/Drafts/20260623-rag.md"
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(
        "# RAG 검색 전략\n\n본문 내용",
        **{"type": "draft", "output": "blog", "status": "draft", "title": title, "source_refs": []},
    )
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return rel


def test_revise_blog_updates_status_to_review(tmp_path):
    rel = _write_draft(tmp_path)
    llm = FakeLLM("다듬어진 본문\n\n## 개선된 단락\n\n내용")
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=llm)

    draft = agent.revise_blog(rel)

    post = frontmatter.loads((tmp_path / rel).read_text(encoding="utf-8"))
    assert post.metadata.get("status") == "review"
    assert draft.rel_path == rel


def test_revise_blog_raises_on_missing(tmp_path):
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=FakeLLM(""))
    with pytest.raises(ValueError, match="초안을 찾지 못했습니다"):
        agent.revise_blog("50_Outputs/Blog/Drafts/없는파일.md")


def test_revise_blog_appends_log(tmp_path):
    rel = _write_draft(tmp_path)
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=FakeLLM("revised content"))
    agent.revise_blog(rel)

    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "revise-blog" in log


# ── WikiBlogAgent.publish_ready ──────────────────────────────────────


def test_publish_ready_changes_status(tmp_path):
    rel = _write_draft(tmp_path)
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=FakeLLM(""))

    draft = agent.publish_ready(rel)

    post = frontmatter.loads((tmp_path / rel).read_text(encoding="utf-8"))
    assert post.metadata.get("status") == "review"
    assert draft.title == "RAG 검색 전략"


def test_publish_ready_raises_on_missing(tmp_path):
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=FakeLLM(""))
    with pytest.raises(ValueError):
        agent.publish_ready("없는파일.md")


# ── ProjectAgent ──────────────────────────────────────────────────────


def test_summarize_project_saves_to_portfolio(tmp_path):
    _write_project_context(tmp_path, "XCoreChat", "XCoreChat RAG 프로젝트 개요")
    llm = FakeLLM("## 프로젝트 개요\n\nXCoreChat은 RAG 기반 챗봇이다.")
    agent = ProjectAgent(settings=_settings(tmp_path), llm=llm)

    result = agent.summarize_project("XCoreChat")

    assert result.path.exists()
    assert "50_Outputs" in str(result.path) and "Portfolio" in str(result.path)
    assert result.project == "XCoreChat"
    assert "RAG 기반 챗봇" in result.text


def test_portfolio_draft_saves_output(tmp_path):
    _write_project_context(tmp_path, "XCoreChat", "XCoreChat 설명")
    llm = FakeLLM("## XCoreChat\n\n포트폴리오 내용")
    agent = ProjectAgent(settings=_settings(tmp_path), llm=llm)

    result = agent.portfolio_draft("XCoreChat")

    assert result.output_type == "portfolio"
    assert result.path.exists()


def test_interview_questions_saves_to_interview(tmp_path):
    _write_project_context(tmp_path, "XCoreChat", "XCoreChat 설명")
    llm = FakeLLM("## Q1. XCoreChat에서 RAG를 어떻게 구현했나요?\n\n**A:** 벡터 검색을 사용했습니다.")
    agent = ProjectAgent(settings=_settings(tmp_path), llm=llm)

    result = agent.interview_questions("XCoreChat")

    assert result.output_type == "interview"
    assert "50_Outputs" in str(result.path) and "Interview" in str(result.path)
    assert result.path.exists()


def test_project_agent_appends_vault_log(tmp_path):
    _write_project_context(tmp_path, "XCoreChat", "내용")
    llm = FakeLLM("요약 결과")
    agent = ProjectAgent(settings=_settings(tmp_path), llm=llm)
    agent.summarize_project("XCoreChat")

    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "XCoreChat" in log


# ── CLI 테스트 ───────────────────────────────────────────────────────


def test_cli_summarize_project(monkeypatch, tmp_path):
    fake_result = SimpleNamespace(
        project="XCoreChat",
        output_type="summary",
        text="## 요약\n\nXCoreChat 프로젝트",
        path=tmp_path / "50_Outputs/Portfolio/summary.md",
        source_refs=[],
    )

    class _FakeAgent:
        def summarize_project(self, project):
            return fake_result

    monkeypatch.setattr(cli, "_project_agent", lambda: _FakeAgent())
    out = runner.invoke(cli.app, ["summarize-project", "XCoreChat"])

    assert out.exit_code == 0
    assert "프로젝트 요약 완료" in out.output


def test_cli_portfolio_draft(monkeypatch, tmp_path):
    fake_result = SimpleNamespace(
        project="XCoreChat",
        output_type="portfolio",
        text="## XCoreChat",
        path=tmp_path / "50_Outputs/Portfolio/portfolio.md",
        source_refs=[],
    )

    class _FakeAgent:
        def portfolio_draft(self, project):
            return fake_result

    monkeypatch.setattr(cli, "_project_agent", lambda: _FakeAgent())
    out = runner.invoke(cli.app, ["portfolio-draft", "XCoreChat"])

    assert out.exit_code == 0
    assert "포트폴리오 초안 완료" in out.output


def test_cli_interview_questions(monkeypatch, tmp_path):
    fake_result = SimpleNamespace(
        project="XCoreChat",
        output_type="interview",
        text="## Q1. 질문\n\n**A:** 답변",
        path=tmp_path / "50_Outputs/Interview/interview.md",
        source_refs=[],
    )

    class _FakeAgent:
        def interview_questions(self, project):
            return fake_result

    monkeypatch.setattr(cli, "_project_agent", lambda: _FakeAgent())
    out = runner.invoke(cli.app, ["interview-questions", "XCoreChat"])

    assert out.exit_code == 0
    assert "면접 질문 초안 완료" in out.output
