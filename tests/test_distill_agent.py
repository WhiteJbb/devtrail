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


def _seed_capture(vault, text="오늘 RAG 검색 정리", project="Devtrail"):
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
                    "project": "Devtrail",
                    "tags": ["rag", "search"],
                    "source_refs": ["00_Inbox/Captures/source.md"],
                }
            ],
            "decisions": [
                {
                    "title": "후보 기반 반영 유지",
                    "summary": "공식 Knowledge 직접 수정을 피한다.",
                    "body": "## 결정\n후보를 먼저 만든다.",
                    "project": "Devtrail",
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
                    "project": "Devtrail",
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
    # 1차 호출은 distill 프롬프트, 2차 호출은 critic 프롬프트
    assert "요청 종류: knowledge" in llm.prompts[0]
    assert "후보 목록" in llm.last_prompt


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


# ── E: critic 게이트 ─────────────────────────────────────────────────────────


class _SeqLLM:
    """호출 순서대로 다른 응답을 반환하는 stub (1차 distill, 2차 critic)."""

    name = "seq"
    model = "seq"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, prompt: str, system: str = "") -> str:
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[idx]


def test_critic_drops_rejected_candidates(tmp_path):
    _seed_capture(tmp_path)
    critic_response = json.dumps({
        "verdicts": [
            {"index": 0, "keep": False, "reason": "커밋 메시지 재서술"},
            {"index": 1, "keep": True, "reason": "근거 있음"},
        ]
    }, ensure_ascii=False)
    llm = _SeqLLM([_distill_response(), critic_response])
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    result = agent.distill_today()

    # _distill_response()는 4개 후보(knowledge/decision/memory_patch/blog_idea) → index 0 탈락
    assert len(result.written) == 3
    assert len(result.dropped) == 1
    assert "커밋 메시지 재서술" in result.dropped[0]


def test_critic_failure_is_fail_open(tmp_path):
    """critic이 JSON을 못 주면 전부 통과한다 — 게이트 오류가 생성을 막지 않는다."""
    _seed_capture(tmp_path)
    llm = _SeqLLM([_distill_response(), "이건 JSON이 아님"])
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    result = agent.distill_today()

    assert len(result.written) == 4
    assert result.dropped == []


def test_critic_missing_verdicts_keeps_all(tmp_path):
    _seed_capture(tmp_path)
    llm = _SeqLLM([_distill_response(), json.dumps({"other": []})])
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    result = agent.distill_today()

    assert len(result.written) == 4
