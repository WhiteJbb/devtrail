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


# ── distill_kinds 스코프 제한 (MCP 세션 노트) ────────────────────────────────


def _seed_mcp_session(vault, when=datetime(2026, 6, 23, 9, 0, 0)):
    """write_session_process가 만드는 것과 같은 스코프 제한 세션 노트를 심는다."""
    return CaptureAgent(settings=_settings(vault), now=when).capture_session(
        project="Devtrail",
        summary_text="## What Changed\n- 훅 크로스플랫폼화",
        from_agent=True,
        source="mcp_session_process",
        needs_distill=True,
        distill_kinds=["knowledge", "blog_idea"],
    )


def test_distill_respects_note_distill_kinds(tmp_path):
    """스코프 제한 세션 노트만 근거인 decision/memory_patch 후보는 버려진다.

    write_session_process가 Decision/MemoryPatch를 이미 구조화 필드에서 추출했으므로
    distill이 같은 노트에서 다시 만들면 중복이다. knowledge/blog_idea는 통과해야 한다
    — 과거 needs_distill=False 방식은 이 둘까지 막아 세션 기록에서 지식 후보가
    영원히 나오지 않았다.
    """
    seeded = _seed_mcp_session(tmp_path)
    response = json.loads(_distill_response())
    for items in response.values():
        for item in items:
            item["source_refs"] = [seeded.rel_path]
    llm = FakeLLM(json.dumps(response, ensure_ascii=False))
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    result = agent.distill_today()

    kinds = sorted(w.spec.kind for w in result.written)
    assert kinds == ["blog_idea", "knowledge"]
    assert len(result.dropped) == 2
    assert all("허용하지 않음" in d for d in result.dropped)
    # 프롬프트 컨텍스트 헤더에도 스코프 힌트가 실린다
    assert "추출허용=knowledge,blog_idea" in llm.prompts[0]


def test_distill_kinds_union_allows_unrestricted_source(tmp_path):
    """무제한 노트(memo)가 근거에 함께 있으면 decision/memory_patch도 유지된다."""
    _seed_capture(tmp_path)  # 무제한 memo (같은 날)
    _seed_mcp_session(tmp_path)
    # _distill_response의 source_refs는 존재하지 않는 경로 → grounding이 fallback으로
    # 두 노트 전체를 refs로 넣으므로, 무제한 memo 덕에 4종 모두 허용된다.
    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    result = agent.distill_today()

    assert sorted(w.spec.kind for w in result.written) == [
        "blog_idea", "decision", "knowledge", "memory_patch",
    ]
    assert result.dropped == []


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
