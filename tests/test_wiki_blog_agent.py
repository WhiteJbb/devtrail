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


# ── BlogIdea 기반 초안 (--idea) ──────────────────────────────────────


def _write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_idea(vault, refs, name="20260820-사이드카-패턴.md"):
    refs_yaml = "\n".join(f"  - {r}" for r in refs)
    _write(
        vault / "60_Candidates/BlogIdeas" / name,
        "---\n"
        "type: candidate\n"
        "candidate_type: blog_idea\n"
        "title: 사이드카 패턴으로 로그 수집 분리하기\n"
        "status: candidate\n"
        "project: homelab\n"
        f"source_refs:\n{refs_yaml}\n"
        "summary: 요약 한 줄\n"
        "---\n"
        "# 사이드카 패턴으로 로그 수집 분리하기\n\n"
        "## 핵심 메시지\n\n로그 수집을 앱에서 떼어내면 배포 주기가 갈라진다.\n\n"
        "## 독자 대상\n\n컨테이너 운영을 시작한 백엔드 개발자\n\n"
        "## 목차 초안\n\n1. 도입\n2. 본론\n3. 결론\n",
    )
    return f"60_Candidates/BlogIdeas/{name}"


def test_write_blog_from_idea_loads_source_refs_in_time_order(tmp_path):
    _write(
        tmp_path / "10_Worklog/Sessions/session-b.md",
        "---\ncreated_at: 2026-08-12\n---\n두번째 세션 본문 SESSION_LATER\n",
    )
    _write(
        tmp_path / "10_Worklog/Sessions/session-a.md",
        "---\ncreated_at: 2026-08-05\n---\n첫번째 세션 본문 SESSION_EARLY\n",
    )
    _write(
        tmp_path / "20_Knowledge/homelab/sidecar.md",
        "---\ntype: knowledge\n---\n사이드카 지식 노트 KNOWLEDGE_NOTE\n",
    )
    idea_rel = _make_idea(
        tmp_path,
        [
            "10_Worklog/Sessions/session-b.md",
            "20_Knowledge/homelab/sidecar.md",
            "10_Worklog/Sessions/session-a.md",
        ],
    )

    llm = FakeLLM(_blog_response())
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=llm)
    draft, warnings = agent.write_blog_from_idea(idea_rel)

    prompt = llm.last_prompt
    assert warnings == []
    # 검색 미리보기가 아니라 refs 원문이 들어간다
    assert "SESSION_EARLY" in prompt and "SESSION_LATER" in prompt and "KNOWLEDGE_NOTE" in prompt
    # 세션 노트는 날짜 오름차순, 그 외 refs는 뒤에
    assert prompt.index("SESSION_EARLY") < prompt.index("SESSION_LATER") < prompt.index("KNOWLEDGE_NOTE")
    # Thesis/Outline 구조
    assert "로그 수집을 앱에서 떼어내면" in prompt
    assert "컨테이너 운영을 시작한 백엔드 개발자" in prompt
    assert "1. 도입" in prompt
    assert draft.path.exists()


def test_write_blog_from_idea_truncates_long_note(tmp_path):
    _write(
        tmp_path / "10_Worklog/Sessions/long.md",
        "---\ncreated_at: 2026-08-05\n---\n" + ("가" * 5000) + "\nTAIL_MARKER\n",
    )
    idea_rel = _make_idea(tmp_path, ["10_Worklog/Sessions/long.md"])

    llm = FakeLLM(_blog_response())
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=llm)
    agent.write_blog_from_idea(idea_rel)

    assert "TAIL_MARKER" not in llm.last_prompt
    assert "이하 생략" in llm.last_prompt


def test_write_blog_from_idea_skips_missing_ref_with_warning(tmp_path):
    _write(tmp_path / "10_Worklog/Sessions/ok.md", "---\ncreated_at: 2026-08-05\n---\n존재하는 노트\n")
    idea_rel = _make_idea(tmp_path, ["10_Worklog/Sessions/ok.md", "10_Worklog/Sessions/gone.md"])

    llm = FakeLLM(_blog_response())
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=llm)
    draft, warnings = agent.write_blog_from_idea(idea_rel)

    assert len(warnings) == 1
    assert "10_Worklog/Sessions/gone.md" in warnings[0]
    assert "존재하는 노트" in llm.last_prompt
    # 없는 ref도 근거 추적을 위해 초안 source_refs에는 남는다
    assert "10_Worklog/Sessions/gone.md" in draft.source_refs


def test_write_blog_from_idea_source_refs_include_idea_file(tmp_path):
    _write(tmp_path / "10_Worklog/Sessions/ok.md", "---\ncreated_at: 2026-08-05\n---\n본문\n")
    idea_rel = _make_idea(tmp_path, ["10_Worklog/Sessions/ok.md"])

    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=FakeLLM(_blog_response()))
    draft, _ = agent.write_blog_from_idea(idea_rel)

    assert draft.source_refs == ["10_Worklog/Sessions/ok.md", idea_rel]
    post = frontmatter.loads(draft.path.read_text(encoding="utf-8"))
    assert post.metadata["source_refs"] == ["10_Worklog/Sessions/ok.md", idea_rel]
    assert post.metadata["project"] == "homelab"


def test_resolve_idea_partial_match(tmp_path):
    idea_rel = _make_idea(tmp_path, [], name="20260820-사이드카-패턴.md")
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=FakeLLM(_blog_response()))

    assert agent.resolve_idea("사이드카") == idea_rel
    assert agent.resolve_idea(idea_rel) == idea_rel


def test_resolve_idea_multiple_matches_fails(tmp_path):
    _make_idea(tmp_path, [], name="20260820-사이드카-패턴.md")
    _make_idea(tmp_path, [], name="20260821-사이드카-로깅.md")
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=FakeLLM(_blog_response()))

    with pytest.raises(ValueError) as err:
        agent.resolve_idea("사이드카")
    assert "20260820-사이드카-패턴.md" in str(err.value)
    assert "20260821-사이드카-로깅.md" in str(err.value)


def test_resolve_idea_no_match_fails(tmp_path):
    _make_idea(tmp_path, [], name="20260820-사이드카-패턴.md")
    agent = WikiBlogAgent(settings=_settings(tmp_path), llm=FakeLLM(_blog_response()))

    with pytest.raises(ValueError):
        agent.resolve_idea("없는후보")


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
            llm_provider="ollama",
            messenger_provider="",
        ),
    )

    out = runner.invoke(cli.app, ["blog", "write", "RAG 검색 전략"])

    assert out.exit_code == 0, out.output
    assert "블로그 초안 생성 완료" in out.output
    assert "50_Outputs/Blog/Drafts/" in out.output
    assert "source_refs: 1개" in out.output


def test_cli_write_blog_with_idea_option(monkeypatch, tmp_path):
    fake_draft = SimpleNamespace(
        title="사이드카 패턴",
        rel_path="50_Outputs/Blog/Drafts/20260820-sidecar.md",
        path=tmp_path / "50_Outputs/Blog/Drafts/20260820-sidecar.md",
        tags=[],
        source_refs=["10_Worklog/Sessions/ok.md", "60_Candidates/BlogIdeas/x.md"],
        body="본문",
    )

    class _FakeAgent:
        def resolve_idea(self, selector):
            return "60_Candidates/BlogIdeas/x.md"

        def write_blog_from_idea(self, idea_rel, project=""):
            return fake_draft, ["source_ref를 찾지 못해 건너뜁니다: 10_Worklog/Sessions/gone.md"]

    monkeypatch.setattr("app.cli.WikiBlogAgent", lambda **kw: _FakeAgent())
    monkeypatch.setattr(
        "app.cli.get_settings",
        lambda: SimpleNamespace(
            obsidian_vault_root=str(tmp_path), llm_provider="ollama", messenger_provider=""
        ),
    )

    out = runner.invoke(cli.app, ["blog", "write", "--idea", "사이드카"])

    assert out.exit_code == 0, out.output
    assert "60_Candidates/BlogIdeas/x.md" in out.output
    assert "gone.md" in out.output
    assert "블로그 초안 생성 완료" in out.output


def test_cli_write_blog_requires_topic_or_idea(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.cli.get_settings",
        lambda: SimpleNamespace(
            obsidian_vault_root=str(tmp_path), llm_provider="ollama", messenger_provider=""
        ),
    )

    out = runner.invoke(cli.app, ["blog", "write"])

    assert out.exit_code != 0
    assert "--idea" in out.output


def test_cli_write_blog_fails_without_vault(monkeypatch):
    monkeypatch.setattr(
        "app.cli.get_settings",
        lambda: SimpleNamespace(
            obsidian_vault_root="",
            llm_provider="",
            messenger_provider="",
        ),
    )

    out = runner.invoke(cli.app, ["blog", "write", "주제"])

    assert out.exit_code != 0
