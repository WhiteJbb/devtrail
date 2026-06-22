"""Phase 7: WikiBlogAgent 테스트 — ContextPack 기반 write-blog."""

import json
from types import SimpleNamespace

import frontmatter
import pytest

from typer.testing import CliRunner

from app import cli
from app.agents.wiki_blog_agent import WikiBlogAgent
from app.config import Settings
from tests.conftest import FakeLLM


runner = CliRunner()


def _settings(vault) -> Settings:
    return Settings(OBSIDIAN_VAULT_PATH=str(vault), LLM_PROVIDER="ollama", MESSENGER_PROVIDER="")


def _blog_response(title: str = "RAG 검색 전략 정리") -> str:
    return json.dumps(
        {
            "title": title,
            "tags": ["rag", "search", "devlog"],
            "body": "## 배경\n\nRAG 검색 환경을 분리했다.\n\n## 결론\n\n성공.",
        },
        ensure_ascii=False,
    )


# ── WikiBlogAgent 단위 테스트 ────────────────────────────────────────


def test_write_blog_saves_to_vault_drafts(tmp_path):
    llm = FakeLLM(_blog_response())
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=llm)

    draft = agent.write_blog("RAG 검색 전략")

    assert draft.path.exists()
    assert draft.rel_path.startswith("50_Outputs/Blog/Drafts/")
    assert "RAG 검색 전략 정리" in draft.title


def test_write_blog_frontmatter_has_source_refs(tmp_path):
    # 관련 노트를 미리 만들어 source_refs가 채워지도록
    knowledge_path = tmp_path / "20_Knowledge" / "AI" / "rag.md"
    knowledge_path.parent.mkdir(parents=True, exist_ok=True)
    knowledge_path.write_text(
        "---\ntype: knowledge\n---\n# RAG\n\nRAG 기초 설명\n",
        encoding="utf-8",
    )

    llm = FakeLLM(_blog_response())
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=llm)
    draft = agent.write_blog("RAG 검색")

    post = frontmatter.loads(draft.path.read_text(encoding="utf-8"))
    assert post.metadata.get("type") == "draft"
    assert post.metadata.get("output") == "blog"
    assert post.metadata.get("status") == "draft"
    # source_refs 가 있어야 한다
    assert post.metadata.get("source_refs") is not None


def test_write_blog_tags_included(tmp_path):
    llm = FakeLLM(_blog_response())
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=llm)
    draft = agent.write_blog("RAG 검색")

    assert "rag" in draft.tags
    assert "search" in draft.tags


def test_write_blog_appends_vault_log(tmp_path):
    llm = FakeLLM(_blog_response())
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=llm)
    agent.write_blog("RAG 검색")

    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "write-blog" in log
    assert "50_Outputs/Blog/Drafts/" in log


def test_write_blog_slug_in_filename(tmp_path):
    llm = FakeLLM(_blog_response("XCoreChat 개발환경 분리 완료"))
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=llm)
    draft = agent.write_blog("XCoreChat 개발환경 분리")

    assert "xcorechat" in draft.rel_path.lower() or "-" in draft.rel_path


def test_write_blog_body_contains_title_h1(tmp_path):
    llm = FakeLLM(_blog_response())
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=llm)
    draft = agent.write_blog("RAG 검색")

    assert draft.body.startswith("# RAG 검색 전략 정리")


# ── CLI write-blog ───────────────────────────────────────────────────


def test_cli_write_blog_success(monkeypatch, tmp_path):
    fake_draft = SimpleNamespace(
        title="RAG 검색 전략",
        rel_path="50_Outputs/Blog/Drafts/20260623-rag.md",
        path=tmp_path / "50_Outputs/Blog/Drafts/20260623-rag.md",
        tags=["rag"],
        source_refs=["40_AgentMemory/00_Profile.md"],
        body="# RAG 검색 전략\n\n본문",
    )

    class _FakeAgent:
        def write_blog(self, topic, project=""):
            return fake_draft

    monkeypatch.setattr("app.cli.WikiBlogAgent", lambda **kw: _FakeAgent())
    monkeypatch.setattr(
        "app.cli.get_settings",
        lambda: SimpleNamespace(
            obsidian_vault_root=str(tmp_path),
            wiki_folder="60_Wiki",
            llm_provider="ollama",
            messenger_provider="",
        ),
    )

    out = runner.invoke(cli.app, ["write-blog", "RAG 검색 전략"])

    assert out.exit_code == 0, out.output
    assert "블로그 초안 생성 완료" in out.output
    assert "50_Outputs/Blog/Drafts/" in out.output
    assert "source_refs: 1개" in out.output


def test_cli_write_blog_fails_without_vault(monkeypatch):
    monkeypatch.setattr(
        "app.cli.get_settings",
        lambda: SimpleNamespace(
            obsidian_vault_root="",
            wiki_folder="60_Wiki",
            llm_provider="",
            messenger_provider="",
        ),
    )

    out = runner.invoke(cli.app, ["write-blog", "주제"])

    assert out.exit_code != 0
