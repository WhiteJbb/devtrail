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


# ── range(weekly) 종합 모드 ──────────────────────────────────────────────────


def _seed_mcp_session_dated(vault, when, needs_distill):
    """지정 날짜로 needs_distill 값을 명시한 세션 노트를 심는다."""
    return CaptureAgent(settings=_settings(vault), now=when).capture_session(
        project="Devtrail",
        summary_text="## What Changed\n- 세션 기록",
        from_agent=True,
        source="mcp_session_process",
        needs_distill=needs_distill,
    )


def test_distill_range_includes_already_marked_sessions(tmp_path):
    """weekly(distill_range)는 daily가 이미 needs_distill=False로 마킹한 세션도
    컨텍스트에 포함해야 한다 — range는 종합 pass이지 미처리 pass가 아니다."""
    seeded = _seed_mcp_session_dated(tmp_path, datetime(2026, 6, 20, 9, 0, 0), needs_distill=False)
    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    result = agent.distill_range(days=7)

    assert seeded.rel_path in llm.prompts[0]
    assert len(result.written) == 4


def test_distill_range_does_not_mark_notes_distilled(tmp_path):
    """range 모드 실행 후에도 어떤 노트의 needs_distill 값도 바뀌지 않는다 —
    생명주기 마킹은 daily 단독 책임으로 남긴다."""
    marked = _seed_mcp_session_dated(tmp_path, datetime(2026, 6, 20, 9, 0, 0), needs_distill=False)
    unmarked = _seed_mcp_session_dated(tmp_path, datetime(2026, 6, 21, 9, 0, 0), needs_distill=True)
    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    agent.distill_range(days=7)

    notes_by_path = {n.path: n for n in agent.wiki_service.scan_notes()}
    assert notes_by_path[marked.rel_path].metadata.get("needs_distill") is False
    assert notes_by_path[unmarked.rel_path].metadata.get("needs_distill") is True


def test_distill_range_prompt_includes_mode_note(tmp_path):
    _seed_capture(tmp_path)
    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    agent.distill_range(days=7)

    assert "종합 모드 안내" in llm.prompts[0]


def test_distill_today_prompt_excludes_mode_note(tmp_path):
    _seed_capture(tmp_path)
    llm = FakeLLM(_distill_response())
    agent = DistillAgent(settings=_settings(tmp_path), llm=llm, now=datetime(2026, 6, 23, 10, 0, 0))

    agent.distill_today()

    assert "종합 모드 안내" not in llm.prompts[0]


# ── Obsidian 링크 연결 ───────────────────────────────────────────────────────


def test_find_related_knowledge_survives_noisy_vault(tmp_path):
    """세션 노트가 많아도 관련 Knowledge 노트를 찾아야 한다.

    prefixes 필터 없이 전역 top-N을 먼저 뽑으면 노트가 많은 폴더(세션 로그)가
    순위를 채워 Knowledge 결과가 잘려나가고, 후보의 '## 관련 노트'가 항상
    '(없음)'이 된다 — 실제 vault에서 wikilink가 16개뿐이던 원인 중 하나.
    """
    knowledge_dir = tmp_path / "20_Knowledge" / "Devtrail"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "RAG-검색-전략.md").write_text(
        "---\ntags: [rag]\n---\n\n# RAG 검색 전략\n\nRAG 검색 Devtrail 정리\n",
        encoding="utf-8",
    )
    sessions = tmp_path / "10_Worklog" / "Sessions"
    sessions.mkdir(parents=True)
    for i in range(30):  # 전역 top-24를 채우고도 남을 노이즈
        (sessions / f"2026-06-2{i % 3}-devtrail-session-{i}.md").write_text(
            f"---\nproject: Devtrail\ncreated_at: 2026-06-23T09:00:0{i % 10}\n---\n\n"
            "# Devtrail 작업 세션\n\nRAG 검색 Devtrail 작업 기록\n",
            encoding="utf-8",
        )
    agent = DistillAgent(settings=_settings(tmp_path), llm=FakeLLM("{}"), now=datetime(2026, 6, 23, 10, 0, 0))
    notes = agent._raw_notes(today_only=True)

    related = agent._find_related_knowledge(notes)

    assert any(n.path.startswith("20_Knowledge/") for n in related)


def test_sanitize_wikilinks_demotes_fabricated_links(tmp_path):
    """존재하지 않는 노트를 가리키는 wikilink는 일반 텍스트로 강등된다."""
    knowledge_dir = tmp_path / "20_Knowledge"
    knowledge_dir.mkdir(parents=True)
    (knowledge_dir / "실존-노트.md").write_text("# 실존\n", encoding="utf-8")
    agent = DistillAgent(settings=_settings(tmp_path), llm=FakeLLM("{}"), now=datetime(2026, 6, 23))

    body = "관련: [[실존-노트]] 그리고 [[지어낸-노트|별칭]] 및 [[stem]]"
    out = agent._sanitize_wikilinks(body, {"실존-노트"})

    assert "[[실존-노트]]" in out
    assert "[[지어낸-노트" not in out and "별칭" in out
    assert "[[stem]]" not in out and "stem" in out


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


# ── blog thread ─────────────────────────────────────────────────────────────


def test_distill_prompt_includes_existing_threads_and_merges(tmp_path):
    """기존 thread가 프롬프트에 제시되고, 같은 슬러그 후보는 새 파일 없이 누적된다."""
    from app.services.candidate_writer import CandidateSpec as Spec, CandidateWriter

    CandidateWriter(tmp_path, now=datetime(2026, 6, 22)).write(
        Spec(
            kind="blog_idea",
            title="홈랩 구축기",
            body="## 핵심 메시지\n\n1일차 이야기\n",
            thread="homelab-build-2026",
            source_refs=["10_Worklog/Sessions/day1.md"],
        )
    )
    _seed_capture(tmp_path)
    response = json.dumps(
        {
            "knowledge": [],
            "decisions": [],
            "memory_patches": [],
            "blog_ideas": [
                {
                    "title": "홈랩 구축기 2일차",
                    "summary": "NAS 연결 삽질",
                    "body": "## 핵심 메시지\n\n2일차 이야기\n",
                    "thread": "homelab-build-2026",
                    "source_refs": [],
                }
            ],
        },
        ensure_ascii=False,
    )
    agent = DistillAgent(
        settings=_settings(tmp_path), llm=FakeLLM(response), now=datetime(2026, 6, 23, 10, 0, 0)
    )

    result = agent.distill_today()

    assert "homelab-build-2026" in agent.llm.prompts[0]
    assert len(list((tmp_path / "60_Candidates/BlogIdeas").glob("*.md"))) == 1
    text = result.written[0].path.read_text(encoding="utf-8")
    assert "title: 홈랩 구축기" in text
    assert "- 2026-06-23: NAS 연결 삽질" in text


def test_thread_continuation_bypasses_critic(tmp_path):
    """기존 thread의 연속인 blog_idea는 critic이 "중복"으로 탈락시켜도 병합돼야 한다.

    critic은 기존 아이디어와 유사한 후보를 중복으로 버리는데, thread 연속 후보는
    중복이 아니라 병합 대상이다 — 탈락하면 새 세션 ref가 thread에 누적되지 못한다.
    """
    from app.services.candidate_writer import CandidateSpec as Spec, CandidateWriter

    CandidateWriter(tmp_path, now=datetime(2026, 6, 22)).write(
        Spec(
            kind="blog_idea",
            title="홈랩 구축기",
            body="## 핵심 메시지\n\n1일차 이야기\n",
            thread="homelab-build-2026",
            source_refs=["10_Worklog/Sessions/day1.md"],
        )
    )
    _seed_capture(tmp_path)
    distill_response = json.dumps(
        {
            "knowledge": [],
            "decisions": [],
            "memory_patches": [],
            "blog_ideas": [
                {
                    "title": "홈랩 구축기 3일차",
                    "summary": "모니터링 추가",
                    "body": "## 핵심 메시지\n\n3일차 이야기\n",
                    "thread": "homelab-build-2026",
                    "source_refs": [],
                }
            ],
        },
        ensure_ascii=False,
    )
    # critic이 유일한 후보(index 0)를 중복으로 탈락시키는 상황
    critic_response = json.dumps(
        {"verdicts": [{"index": 0, "keep": False, "reason": "기존 아이디어와 중복"}]},
        ensure_ascii=False,
    )
    agent = DistillAgent(
        settings=_settings(tmp_path),
        llm=_SeqLLM([distill_response, critic_response]),
        now=datetime(2026, 6, 23, 10, 0, 0),
    )

    result = agent.distill_today()

    assert len(result.written) == 1
    assert result.dropped == []
    text = result.written[0].path.read_text(encoding="utf-8")
    assert "title: 홈랩 구축기" in text
    assert "- 2026-06-23: 모니터링 추가" in text
