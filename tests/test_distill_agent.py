import json
from datetime import datetime
from types import SimpleNamespace

from typer.testing import CliRunner

from app import cli
from app.agents.capture_agent import CaptureAgent
from app.agents.distill_agent import DistillAgent
from app.config import Settings
from app.services.candidate_writer import CandidateSpec, CandidateWriteResult
from tests.conftest import FakeLLM


runner = CliRunner()


def _settings(vault):
    return Settings(OBSIDIAN_VAULT_PATH=str(vault), LLM_PROVIDER="ollama", MESSENGER_PROVIDER="")


def _seed_capture(vault, text="오늘 RAG 검색 정리", project="WorkAgent"):
    CaptureAgent(
        settings=_settings(vault),
        now=datetime(2026, 6, 23, 9, 10, 11),
    ).capture(text, project=project)


def _distill_response():
    return json.dumps(
        {
            "knowledge": [
                {
                    "title": "RAG 검색 전략",
                    "summary": "검색 전략을 재사용 가능한 지식으로 정리",
                    "body": "## 요약\nBM25와 벡터 검색을 함께 검토했다.",
                    "project": "WorkAgent",
                    "tags": ["rag", "search"],
                    "source_refs": ["00_Inbox/Captures/source.md"],
                }
            ],
            "decisions": [
                {
                    "title": "후보 기반 반영 유지",
                    "summary": "공식 Knowledge 직접 수정을 피한다.",
                    "body": "## 결정\n후보를 먼저 만든다.",
                    "project": "WorkAgent",
                    "tags": ["decision"],
                    "source_refs": ["00_Inbox/Captures/source.md"],
                }
            ],
            "memory_patches": [
                {
                    "title": "작성 규칙 기억",
                    "summary": "근거 없는 내용을 피한다.",
                    "body": "- source_refs를 유지한다.",
                    "project": "",
                    "tags": ["memory"],
                    "source_refs": ["00_Inbox/Captures/source.md"],
                }
            ],
            "blog_ideas": [
                {
                    "title": "RAG 검색 정리 글감",
                    "summary": "작업 기록 기반 글감",
                    "body": "- 문제\n- 해결\n- 배운 점",
                    "project": "WorkAgent",
                    "tags": ["blog-idea"],
                    "source_refs": ["00_Inbox/Captures/source.md"],
                }
            ],
        },
        ensure_ascii=False,
    )


def test_distill_today_writes_candidates_only(tmp_path):
    _seed_capture(tmp_path)
    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    result = agent.distill_today()

    assert len(result.written) == 4
    rels = [item.rel_path for item in result.written]
    assert any(path.startswith("60_Candidates/Knowledge/") for path in rels)
    assert any(path.startswith("60_Candidates/Decisions/") for path in rels)
    assert any(path.startswith("60_Candidates/MemoryPatches/") for path in rels)
    assert any(path.startswith("60_Candidates/BlogIdeas/") for path in rels)
    assert not list((tmp_path / "20_Knowledge").rglob("*.md"))

    first_text = result.written[0].path.read_text(encoding="utf-8")
    assert "type: candidate" in first_text
    assert "candidate_type: knowledge" in first_text
    assert "RAG 검색 전략" in first_text
    assert "source_refs" in first_text

    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "distill | RAG 검색 전략" in log


def test_suggest_knowledge_filters_to_knowledge(tmp_path):
    _seed_capture(tmp_path)
    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    result = agent.suggest_knowledge()

    assert len(result.written) == 1
    assert result.written[0].rel_path.startswith("60_Candidates/Knowledge/")
    assert "요청 종류: knowledge" in llm.last_prompt


def test_distill_today_without_today_sources_returns_empty(tmp_path):
    _seed_capture(tmp_path)
    agent = DistillAgent(
        settings=_settings(tmp_path),
        llm=FakeLLM(_distill_response()),
        now=datetime(2026, 6, 24, 10, 0, 0),
    )

    result = agent.distill_today()

    assert result.written == []
    assert result.source_refs == []


def test_cli_suggest_blog_topics(monkeypatch):
    spec = CandidateSpec(kind="blog_idea", title="글감", body="본문")
    result = SimpleNamespace(
        written=[
            CandidateWriteResult(
                spec=spec,
                path="vault/60_Candidates/BlogIdeas/글감.md",
                rel_path="60_Candidates/BlogIdeas/글감.md",
            )
        ]
    )

    class _FakeDistill:
        def suggest_blog_topics(self):
            return result

    monkeypatch.setattr(cli, "_distill_agent", lambda: _FakeDistill())

    out = runner.invoke(cli.app, ["suggest-blog-topics"])

    assert out.exit_code == 0
    assert "후보 1개 생성" in out.output
    assert "60_Candidates/BlogIdeas/글감.md" in out.output
