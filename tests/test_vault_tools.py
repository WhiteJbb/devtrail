"""app/vault_tools.py 서비스 레이어 테스트 (docs/service-improvement-plan.md P2)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import frontmatter
import pytest

from app import vault_tools


def _settings(tmp_path: Path):
    return SimpleNamespace(
        obsidian_vault_root=str(tmp_path),
        git_diff_max_chars=800,
    )


def _write(vault: Path, rel_path: str, body: str = "본문", **meta) -> Path:
    path = vault / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"type": "note", "title": Path(rel_path).stem, **meta}
    path.write_text(frontmatter.dumps(frontmatter.Post(body, **metadata)), encoding="utf-8")
    return path


# ── read_note / scope ────────────────────────────────────────────────────────


def test_read_note_rejects_scope_outside_paths(tmp_path):
    _write(tmp_path, "00_Inbox/Memos/secret.md")
    settings = _settings(tmp_path)
    with pytest.raises(vault_tools.VaultScopeError):
        vault_tools.read_note("00_Inbox/Memos/secret.md", settings=settings)


def test_read_note_rejects_dotdot_escape(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(vault_tools.VaultScopeError):
        vault_tools.read_note("20_Knowledge/../../etc/passwd", settings=settings)


def test_read_note_rejects_absolute_path(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(vault_tools.VaultScopeError):
        vault_tools.read_note(str(tmp_path / "20_Knowledge/x.md"), settings=settings)


def test_read_note_reads_allowed_scope(tmp_path):
    _write(tmp_path, "20_Knowledge/rag.md", body="RAG 노트 본문")
    settings = _settings(tmp_path)
    content = vault_tools.read_note("20_Knowledge/rag.md", settings=settings)
    assert "RAG 노트 본문" in content


def test_read_note_missing_file_raises(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(vault_tools.VaultScopeError):
        vault_tools.read_note("20_Knowledge/없음.md", settings=settings)


def test_read_note_directory_path_raises_instead_of_os_error(tmp_path):
    """스코프 안이지만 디렉터리인 경로는 OS 예외 대신 VaultScopeError여야 한다(P3.4)."""
    (tmp_path / "20_Knowledge" / "AI").mkdir(parents=True)
    settings = _settings(tmp_path)
    with pytest.raises(vault_tools.VaultScopeError):
        vault_tools.read_note("20_Knowledge/AI", settings=settings)


def test_read_note_falls_back_on_non_utf8_encoding(tmp_path):
    """cp949 등으로 저장된 노트도 UnicodeDecodeError 없이 읽혀야 한다(P3.4)."""
    path = tmp_path / "20_Knowledge" / "legacy.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("한글 노트".encode("cp949"))
    settings = _settings(tmp_path)
    content = vault_tools.read_note("20_Knowledge/legacy.md", settings=settings)
    assert content  # 깨지더라도 예외 없이 문자열을 반환해야 한다


# ── search_vault ─────────────────────────────────────────────────────────────


def test_search_vault_excludes_out_of_scope_notes(tmp_path):
    _write(tmp_path, "00_Inbox/Memos/foo.md", body="검색어 포함 내용")
    _write(tmp_path, "20_Knowledge/foo.md", body="검색어 포함 내용")
    settings = _settings(tmp_path)
    hits = vault_tools.search_vault("검색어", settings=settings)
    paths = [h.path for h in hits]
    assert "20_Knowledge/foo.md" in paths
    assert not any(p.startswith("00_Inbox/") for p in paths)


def test_search_vault_includes_candidate_status(tmp_path):
    _write(tmp_path, "60_Candidates/Knowledge/foo.md", body="검색어 포함")
    settings = _settings(tmp_path)
    hits = vault_tools.search_vault("검색어", settings=settings)
    assert hits and hits[0].status == "candidate"


def test_search_vault_stable_sorted_before_candidate(tmp_path):
    _write(tmp_path, "60_Candidates/Knowledge/cand.md", body="공통검색어 후보")
    _write(tmp_path, "20_Knowledge/stable.md", body="공통검색어 안정")
    settings = _settings(tmp_path)
    hits = vault_tools.search_vault("공통검색어", settings=settings)
    statuses = [h.status for h in hits]
    assert statuses.index("stable") < statuses.index("candidate")


def test_search_vault_scope_note_not_crowded_out_by_out_of_scope_notes(tmp_path):
    """스코프 밖 노트가 많아도 스코프 안 결과가 top-N에서 밀려나면 안 된다(P3.3).

    사후 필터링(전역 top-N을 먼저 뽑고 걸러내기)이면 00_Inbox/10_Worklog처럼
    노트가 많은 폴더가 default limit(10)을 다 채워, 실제로 스코프 안에 있는
    유일한 결과가 아예 반환되지 않을 수 있다.
    """
    for i in range(45):
        _write(tmp_path, f"10_Worklog/Sessions/session-{i:02d}.md", body="프로젝트희귀검색어 반복 등장")
    _write(tmp_path, "20_Knowledge/rag.md", body="프로젝트희귀검색어 관련 지식")

    settings = _settings(tmp_path)
    hits = vault_tools.search_vault("프로젝트희귀검색어", settings=settings)  # 기본 limit=10
    assert any(h.path == "20_Knowledge/rag.md" for h in hits)


# ── record_note ──────────────────────────────────────────────────────────────


def test_record_note_writes_only_to_candidates(tmp_path):
    settings = _settings(tmp_path)
    result = vault_tools.record_note("knowledge", "테스트 지식", "본문 내용", settings=settings)
    assert result.rel_path.startswith("60_Candidates/")


def test_record_note_rejects_memory_patch_kind(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(vault_tools.VaultScopeError):
        vault_tools.record_note("memory_patch", "제목", "본문", settings=settings)


def test_record_note_rejects_session_handoff_kind(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(vault_tools.VaultScopeError):
        vault_tools.record_note("session_handoff", "제목", "본문", settings=settings)


# ── record_agent_improvement ─────────────────────────────────────────────────


def test_record_agent_improvement_writes_memory_patch_with_required_fields(tmp_path):
    settings = _settings(tmp_path)
    result = vault_tools.record_agent_improvement(
        project="Devtrail", issue="경로 확인 누락", improvement="먼저 경로를 확인한다", evidence="3회 발생", settings=settings
    )
    post = frontmatter.loads((tmp_path / result.rel_path).read_text(encoding="utf-8"))
    assert post.metadata["candidate_type"] == "memory_patch"
    assert post.metadata["evidence"] == "3회 발생"
    assert post.metadata["scope"] == "project"
    assert post.metadata["confidence"] == "unspecified"
    assert post.metadata["requires_user_review"] is True


# ── write_work_plan / write_session_process ─────────────────────────────────


def test_write_work_plan_creates_session_handoff_candidate(tmp_path):
    settings = _settings(tmp_path)
    result = vault_tools.write_work_plan(
        project="Devtrail",
        goal="MCP 서버 구현",
        context_read="설계 문서",
        scope="app/vault_tools.py",
        approach="단계별 구현",
        risks="없음",
        session_id="sess-001",
        settings=settings,
    )
    assert "SessionHandoffs/Devtrail" in result.rel_path
    post = frontmatter.loads((tmp_path / result.rel_path).read_text(encoding="utf-8"))
    assert post.metadata["handoff_type"] == "plan"
    assert post.metadata["session_id"] == "sess-001"


def test_write_session_process_double_writes_worklog(tmp_path):
    settings = _settings(tmp_path)
    result = vault_tools.write_session_process(
        project="Devtrail",
        what_changed="vault_tools.py 추가",
        files_touched="app/vault_tools.py",
        project_decisions={"decision": "", "final_judge": "unresolved"},
        implementation_trace="구현 흐름",
        agent_execution_notes={},
        docs_update_candidates="",
        next_session="테스트 마저 작성",
        learning_recovery={},
        session_id="sess-002",
        settings=settings,
    )
    assert (tmp_path / result.process.rel_path).exists()
    assert (tmp_path / result.worklog_rel_path).exists()
    assert result.worklog_rel_path.startswith("10_Worklog/Sessions/")


def test_write_session_process_worklog_is_not_marked_for_redistill(tmp_path):
    """write_session_process가 남긴 worklog 노트는 needs_distill=False여야 한다(P1.3).

    True로 남으면 nightly distill이 이미 구조화된 Process를 재추출해 방금 분리 생성한
    Decision/MemoryPatch와 중복 후보를 만든다.
    """
    settings = _settings(tmp_path)
    result = vault_tools.write_session_process(
        project="Devtrail", what_changed="x", files_touched="x", project_decisions={},
        implementation_trace="x", agent_execution_notes={}, docs_update_candidates="",
        next_session="", learning_recovery={}, session_id="sess-nd", settings=settings,
    )
    post = frontmatter.loads((tmp_path / result.worklog_rel_path).read_text(encoding="utf-8"))
    assert post.metadata["needs_distill"] is False


def test_write_session_process_memory_patch_updated_for_same_session(tmp_path):
    """같은 세션(같은 날·같은 프로젝트)의 재기록은 patch를 갱신해야 한다.

    이전에는 dedup=False로 항상 새 파일을 만들어 재기록 시 ' (2)' 후보가 쌓였다.
    upsert_exact는 제목이 정확히 같은 후보만 갱신하고, 날짜가 다른(다른 세션)
    후보는 건드리지 않는다(P1.1의 세션 간 유실 방지와 양립).
    """
    settings = _settings(tmp_path)
    notes1 = {"next_checks": "테스트 먼저 실행", "evidence": "로그 확인"}
    notes2 = {"next_checks": "테스트와 린트를 먼저 실행", "evidence": "로그 확인"}

    result1 = vault_tools.write_session_process(
        project="Devtrail", what_changed="1차 변경", files_touched="a.py",
        project_decisions={}, implementation_trace="x", agent_execution_notes=notes1,
        docs_update_candidates="", next_session="", learning_recovery={},
        session_id="sess-mp-1", settings=settings,
    )
    result2 = vault_tools.write_session_process(
        project="Devtrail", what_changed="2차 변경", files_touched="b.py",
        project_decisions={}, implementation_trace="x", agent_execution_notes=notes2,
        docs_update_candidates="", next_session="", learning_recovery={},
        session_id="sess-mp-1", settings=settings,
    )

    assert result1.memory_patch is not None
    assert result2.memory_patch is not None
    # 같은 날 같은 프로젝트 → 제목 동일 → 갱신 (새 파일 없음)
    assert result1.memory_patch.rel_path == result2.memory_patch.rel_path
    content = (tmp_path / result2.memory_patch.rel_path).read_text(encoding="utf-8")
    assert "테스트와 린트를 먼저 실행" in content


def test_write_session_process_memory_patch_distills_lessons_only(tmp_path):
    """Lessons 패치에는 일반화 가능한 필드(next_checks/better_approach)만 들어간다.

    막힌 점·실수는 세션 한정 사실이라 Process에만 남는다 — 통째로 append하면
    Lessons가 세션 보일러플레이트로 비대해진다.
    """
    settings = _settings(tmp_path)
    result = vault_tools.write_session_process(
        project="Devtrail", what_changed="x", files_touched="x",
        project_decisions={}, implementation_trace="x",
        agent_execution_notes={
            "blocked": "머지 권한 차단",
            "mistakes": "경로 오탐",
            "next_checks": "briefing은 실측 먼저",
            "better_approach": "임시 repo 케이스 검증",
        },
        docs_update_candidates="", next_session="", learning_recovery={},
        session_id="sess-distill", settings=settings,
    )
    assert result.memory_patch is not None
    content = (tmp_path / result.memory_patch.rel_path).read_text(encoding="utf-8")
    assert "briefing은 실측 먼저" in content
    assert "임시 repo 케이스 검증" in content
    assert "머지 권한 차단" not in content
    assert "경로 오탐" not in content
    # 세션 한정 사실은 Process 기록에는 남아야 한다
    process_content = (tmp_path / result.process.rel_path).read_text(encoding="utf-8")
    assert "머지 권한 차단" in process_content


def test_write_session_process_no_memory_patch_for_session_specific_notes_only(tmp_path):
    """blocked/mistakes만 있으면 Lessons 패치를 만들지 않는다 (Process에만 기록)."""
    settings = _settings(tmp_path)
    result = vault_tools.write_session_process(
        project="Devtrail", what_changed="x", files_touched="x",
        project_decisions={}, implementation_trace="x",
        agent_execution_notes={"blocked": "권한 차단", "mistakes": "오탐"},
        docs_update_candidates="", next_session="", learning_recovery={},
        session_id="sess-no-patch", settings=settings,
    )
    assert result.memory_patch is None


def test_write_session_process_no_decision_when_final_judge_key_missing(tmp_path):
    """final_judge 키를 아예 안 넘기면 Decision 후보가 생기면 안 된다(P1.2).

    본문 렌더링은 누락 시 'unresolved'로 표기하는데, 가드가 빈 문자열을 걸러내지
    못하면 본문은 미해결이라 적으면서 후보는 생성되는 모순이 생긴다.
    """
    settings = _settings(tmp_path)
    result = vault_tools.write_session_process(
        project="Devtrail", what_changed="x", files_touched="x",
        project_decisions={"decision": "아직 논의 중인 결정"},  # final_judge 키 자체가 없음
        implementation_trace="x", agent_execution_notes={}, docs_update_candidates="",
        next_session="", learning_recovery={}, session_id="sess-fj-missing", settings=settings,
    )
    assert result.decision is None


def test_write_session_process_splits_decision_when_present(tmp_path):
    settings = _settings(tmp_path)
    result = vault_tools.write_session_process(
        project="Devtrail",
        what_changed="x",
        files_touched="x",
        project_decisions={
            "decision": "MCP 서버는 stdio로 구현한다",
            "reason": "Claude Desktop 호환",
            "alternatives": "HTTP",
            "final_judge": "user",
        },
        implementation_trace="x",
        agent_execution_notes={},
        docs_update_candidates="",
        next_session="",
        learning_recovery={},
        session_id="sess-003",
        settings=settings,
    )
    assert result.decision is not None
    assert result.decision.rel_path.startswith("60_Candidates/Decisions/")


def test_write_session_process_no_decision_when_unresolved(tmp_path):
    settings = _settings(tmp_path)
    result = vault_tools.write_session_process(
        project="Devtrail",
        what_changed="x",
        files_touched="x",
        project_decisions={"decision": "아직 확정 안됨", "final_judge": "unresolved"},
        implementation_trace="x",
        agent_execution_notes={},
        docs_update_candidates="",
        next_session="",
        learning_recovery={},
        session_id="sess-004",
        settings=settings,
    )
    assert result.decision is None


def test_write_session_process_splits_memory_patch_when_notes_present(tmp_path):
    settings = _settings(tmp_path)
    result = vault_tools.write_session_process(
        project="Devtrail",
        what_changed="x",
        files_touched="x",
        project_decisions={},
        implementation_trace="x",
        agent_execution_notes={"next_checks": "경로부터 확인", "evidence": "로그 확인", "confidence": "high"},
        docs_update_candidates="",
        next_session="",
        learning_recovery={},
        session_id="sess-005",
        settings=settings,
    )
    assert result.memory_patch is not None
    post = frontmatter.loads((tmp_path / result.memory_patch.rel_path).read_text(encoding="utf-8"))
    assert post.metadata["confidence"] == "high"


def test_write_session_process_no_memory_patch_when_notes_empty(tmp_path):
    settings = _settings(tmp_path)
    result = vault_tools.write_session_process(
        project="Devtrail",
        what_changed="x",
        files_touched="x",
        project_decisions={},
        implementation_trace="x",
        agent_execution_notes={},
        docs_update_candidates="",
        next_session="",
        learning_recovery={},
        session_id="sess-006",
        settings=settings,
    )
    assert result.memory_patch is None


def test_session_handoffs_same_title_not_deduped_across_plan_and_process(tmp_path):
    settings = _settings(tmp_path)
    vault_tools.write_work_plan(
        project="Devtrail", goal="g", context_read="c", scope="s", approach="a", risks="r",
        session_id="sess-007", settings=settings,
    )
    vault_tools.write_work_plan(
        project="Devtrail", goal="g2", context_read="c", scope="s", approach="a", risks="r",
        session_id="sess-008", settings=settings,
    )
    handoff_dir = tmp_path / "60_Candidates/SessionHandoffs/Devtrail"
    assert len(list(handoff_dir.glob("*.md"))) == 2


def test_write_session_process_reattaches_orphan_plan_session_id(tmp_path):
    settings = _settings(tmp_path)
    vault_tools.write_work_plan(
        project="Devtrail", goal="g", context_read="c", scope="s", approach="a", risks="r",
        session_id="orphan-plan-1", settings=settings,
    )
    # 서버가 재시작돼 다른 session_id로 Process를 쓰려는 상황을 시뮬레이션
    result = vault_tools.write_session_process(
        project="Devtrail",
        what_changed="x", files_touched="x", project_decisions={}, implementation_trace="x",
        agent_execution_notes={}, docs_update_candidates="", next_session="",
        learning_recovery={}, session_id="new-server-session", settings=settings,
    )
    assert result.session_id == "orphan-plan-1"


def test_write_session_process_does_not_reattach_plan_older_than_24h(tmp_path):
    """24시간을 넘긴 미짝 Plan에는 재귀속하지 않아야 한다(P3.2).

    재귀속은 "같은 세션 중 MCP 서버 재시작" 복구가 목적이므로, 상한이 없으면
    몇 주 전 무관한 세션의 미짝 Plan에 오늘의 Process가 잘못 엮인다.
    """
    from datetime import datetime, timedelta

    from app.services.candidate_writer import CandidateSpec, CandidateWriter

    settings = _settings(tmp_path)
    stale_time = datetime.now() - timedelta(hours=25)
    CandidateWriter(tmp_path, now=stale_time).write(
        CandidateSpec(
            kind="session_handoff", title="Plan 오래된 미짝", body="x",
            project="Devtrail", handoff_type="plan", session_id="stale-orphan",
        )
    )

    result = vault_tools.write_session_process(
        project="Devtrail", what_changed="x", files_touched="x", project_decisions={},
        implementation_trace="x", agent_execution_notes={}, docs_update_candidates="",
        next_session="", learning_recovery={}, session_id="brand-new-session", settings=settings,
    )
    assert result.session_id == "brand-new-session"


def test_write_session_process_reattaches_plan_within_24h(tmp_path):
    from datetime import datetime, timedelta

    from app.services.candidate_writer import CandidateSpec, CandidateWriter

    settings = _settings(tmp_path)
    recent_time = datetime.now() - timedelta(hours=1)
    CandidateWriter(tmp_path, now=recent_time).write(
        CandidateSpec(
            kind="session_handoff", title="Plan 최근 미짝", body="x",
            project="Devtrail", handoff_type="plan", session_id="recent-orphan",
        )
    )

    result = vault_tools.write_session_process(
        project="Devtrail", what_changed="x", files_touched="x", project_decisions={},
        implementation_trace="x", agent_execution_notes={}, docs_update_candidates="",
        next_session="", learning_recovery={}, session_id="brand-new-session-2", settings=settings,
    )
    assert result.session_id == "recent-orphan"


# ── list-candidates 기본 출력 제외 (CuratorAgent 연동) ───────────────────────


def test_curator_list_candidates_excludes_session_handoffs_by_default(tmp_path):
    from app.agents.curator_agent import CuratorAgent
    from app.config import Settings

    settings = Settings(OBSIDIAN_VAULT_PATH=str(tmp_path), LLM_PROVIDER="", MESSENGER_PROVIDER="")
    vault_tools.write_work_plan(
        project="Devtrail", goal="g", context_read="c", scope="s", approach="a", risks="r",
        session_id="sess-x", settings=settings,
    )
    vault_tools.record_note("knowledge", "일반 지식", "본문", settings=settings)

    agent = CuratorAgent(settings=settings)
    default_items = agent.list_candidates()
    all_items = agent.list_candidates(include_session_handoffs=True)

    assert all(i.kind != "session_handoff" for i in default_items)
    assert any(i.kind == "session_handoff" for i in all_items)


# ── get_project_briefing ─────────────────────────────────────────────────────


def test_get_project_briefing_tolerates_non_dict_vault_json(tmp_path):
    """.claude/vault.json이 스칼라/배열이어도 AttributeError 없이 폴백해야 한다(P3.1)."""
    repo_dir = tmp_path / "repo"
    (repo_dir / ".claude").mkdir(parents=True)
    (repo_dir / ".claude" / "vault.json").write_text('"devtrail"', encoding="utf-8")

    settings = _settings(tmp_path)
    briefing = vault_tools.get_project_briefing(str(repo_dir), settings=settings)
    assert briefing.matched is False


def test_get_project_briefing_tolerates_array_vault_json(tmp_path):
    repo_dir = tmp_path / "repo"
    (repo_dir / ".claude").mkdir(parents=True)
    (repo_dir / ".claude" / "vault.json").write_text('["devtrail"]', encoding="utf-8")

    settings = _settings(tmp_path)
    briefing = vault_tools.get_project_briefing(str(repo_dir), settings=settings)
    assert briefing.matched is False


def test_get_project_briefing_no_match_returns_candidates_without_context(tmp_path):
    _write(tmp_path, "30_Projects/Devtrail/Context.md", body="Devtrail 컨텍스트")
    settings = _settings(tmp_path)
    briefing = vault_tools.get_project_briefing("완전히다른이름", settings=settings)
    assert briefing.matched is False
    assert "Devtrail" in briefing.candidates


def test_get_project_briefing_cold_start_returns_global_memory_only(tmp_path):
    settings = _settings(tmp_path)
    briefing = vault_tools.get_project_briefing("Devtrail", settings=settings)
    # ProjectMemory에 Devtrail이 전혀 없으면 매칭 실패로 후보 목록 반환(빈 목록)
    assert briefing.matched is False


def test_get_project_briefing_finds_unregistered_project_via_handoff_folder(tmp_path):
    """ProjectMemory 등록 없이 write_work_plan만 호출한 프로젝트도 briefing에 보여야 한다(P3.5).

    write_work_plan은 임의 project 문자열을 받아 SessionHandoffs/<slug>/에 쓰지만,
    기존 briefing은 30_Projects 등록 또는 vault.json이 있어야만 그 폴더를 읽어
    핸드오프가 briefing에 영원히 노출되지 않았다.
    """
    settings = _settings(tmp_path)
    vault_tools.write_work_plan(
        project="NewProject", goal="목표", context_read="c", scope="s", approach="a", risks="r",
        session_id="sess-new", settings=settings,
    )
    briefing = vault_tools.get_project_briefing("NewProject", settings=settings)
    assert briefing.matched is True
    assert briefing.project == "NewProject"
    assert "Recent Session Handoff" in briefing.text


def test_write_and_read_project_name_case_insensitive_same_folder(tmp_path):
    """소문자로 쓰고 다른 대소문자로 조회해도 같은 SessionHandoffs 폴더를 봐야 한다(P3.5)."""
    settings = _settings(tmp_path)
    vault_tools.write_work_plan(
        project="devtrail", goal="목표", context_read="c", scope="s", approach="a", risks="r",
        session_id="sess-case", settings=settings,
    )
    briefing = vault_tools.get_project_briefing("Devtrail", settings=settings)
    assert briefing.matched is True
    assert "Recent Session Handoff" in briefing.text


def test_write_session_process_canonicalizes_project_casing_when_registered(tmp_path):
    """registry에 "Devtrail"이 있으면 project="devtrail"로 써도 같은 폴더에 기록돼야 한다(P3.5)."""
    _write(tmp_path, "30_Projects/Devtrail/Context.md", body="컨텍스트")
    settings = _settings(tmp_path)
    result = vault_tools.write_work_plan(
        project="devtrail", goal="목표", context_read="c", scope="s", approach="a", risks="r",
        session_id="sess-canon", settings=settings,
    )
    assert result.rel_path.startswith("60_Candidates/SessionHandoffs/Devtrail/")


def test_get_project_briefing_matches_registered_project(tmp_path):
    _write(tmp_path, "30_Projects/Devtrail/Context.md", body="Devtrail 프로젝트 컨텍스트 본문")
    settings = _settings(tmp_path)
    briefing = vault_tools.get_project_briefing("Devtrail", settings=settings)
    assert briefing.matched is True
    assert briefing.project == "Devtrail"
    assert "Devtrail 프로젝트 컨텍스트 본문" in briefing.text


def test_get_project_briefing_orders_handoffs_by_time_not_filename(tmp_path):
    """같은 날 만들어진 handoff는 파일명 알파벳순이 아니라 실제 생성 시각순이어야 한다(P2.1).

    날짜만(%Y-%m-%d) 기록되면 같은 날 handoff끼리 동점 처리되어, stable sort가
    파일명(글롭 열거 순서, 곧 알파벳순) 순서를 그대로 유지해버린다. 아침 Plan을
    알파벳상 앞선("AAA") 제목으로, 저녁 Plan을 뒤선("ZZZ") 제목으로 만들어
    시간순(저녁이 최신)과 알파벳순(아침이 먼저)이 어긋나게 한다.
    """
    from datetime import datetime as _dt

    from app.services.candidate_writer import CandidateSpec, CandidateWriter

    _write(tmp_path, "30_Projects/Devtrail/Context.md", body="컨텍스트")
    morning_writer = CandidateWriter(tmp_path, now=_dt(2026, 7, 6, 9, 0, 0))
    evening_writer = CandidateWriter(tmp_path, now=_dt(2026, 7, 6, 18, 0, 0))
    morning_writer.write(
        CandidateSpec(
            kind="session_handoff", title="AAA 아침 세션", body="아침 작업",
            project="Devtrail", handoff_type="plan", session_id="s-morning",
        )
    )
    evening_writer.write(
        CandidateSpec(
            kind="session_handoff", title="ZZZ 저녁 세션", body="저녁 작업",
            project="Devtrail", handoff_type="plan", session_id="s-evening",
        )
    )

    settings = _settings(tmp_path)
    briefing = vault_tools.get_project_briefing("Devtrail", settings=settings)
    idx_evening = briefing.text.index("ZZZ 저녁 세션")
    idx_morning = briefing.text.index("AAA 아침 세션")
    assert idx_evening < idx_morning, "실제 최신(저녁) handoff가 먼저 나와야 한다"


def test_get_project_briefing_includes_recent_plan_process(tmp_path):
    _write(tmp_path, "30_Projects/Devtrail/Context.md", body="컨텍스트")
    settings = _settings(tmp_path)
    vault_tools.write_work_plan(
        project="Devtrail", goal="목표 문자열", context_read="c", scope="s", approach="a", risks="r",
        session_id="sess-a", settings=settings,
    )
    briefing = vault_tools.get_project_briefing("Devtrail", settings=settings)
    assert "Recent Session Handoff" in briefing.text


def test_get_project_briefing_warns_on_unpaired_plan(tmp_path):
    _write(tmp_path, "30_Projects/Devtrail/Context.md", body="컨텍스트")
    settings = _settings(tmp_path)
    vault_tools.write_work_plan(
        project="Devtrail", goal="목표", context_read="c", scope="s", approach="a", risks="r",
        session_id="sess-orphan", settings=settings,
    )
    briefing = vault_tools.get_project_briefing("Devtrail", settings=settings)
    assert "미짝 Plan" in briefing.text


# ── A: 인덱스 우선 briefing / D: 신선도·Plan 리마인더 ────────────────────────


def _write_project_context(vault: Path, project: str, body: str, updated_at: str = "") -> None:
    meta = {"type": "project_context", "project": project, "status": "active"}
    if updated_at:
        meta["updated_at"] = updated_at
    _write(vault, f"30_Projects/{project}/Context.md", body=body, **meta)


def test_briefing_truncates_long_context_with_read_note_pointer(tmp_path):
    _write_project_context(tmp_path, "Devtrail", "배경 " * 500)
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))

    assert 'read_note("30_Projects/Devtrail/Context.md")' in briefing.text
    # 전문(약 1500자)이 통째로 들어가지 않는다
    assert briefing.text.count("배경") < 400


def test_briefing_short_context_has_no_pointer(tmp_path):
    _write_project_context(tmp_path, "Devtrail", "짧은 배경")
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "짧은 배경" in briefing.text
    assert "_전문: read_note" not in briefing.text


def test_briefing_lists_reference_notes(tmp_path):
    _write_project_context(tmp_path, "Devtrail", "배경")
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "## 참고 노트" in briefing.text
    assert "- 30_Projects/Devtrail/Context.md" in briefing.text


def test_briefing_warns_on_stale_context(tmp_path):
    _write_project_context(tmp_path, "Devtrail", "배경", updated_at="2026-01-01")
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "Context 신선도 경고" in briefing.text


def test_briefing_no_warning_for_fresh_context(tmp_path):
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    _write_project_context(tmp_path, "Devtrail", "배경", updated_at=today)
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "Context 신선도 경고" not in briefing.text


def test_briefing_no_warning_without_updated_at(tmp_path):
    """updated_at이 없으면 오탐 경고를 내지 않는다."""
    _write_project_context(tmp_path, "Devtrail", "배경")
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "Context 신선도 경고" not in briefing.text


def test_briefing_reminds_plan_when_none_today(tmp_path):
    _write_project_context(tmp_path, "Devtrail", "배경")
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "write_work_plan" in briefing.text


def test_briefing_no_plan_reminder_when_todays_plan_exists(tmp_path):
    from datetime import datetime
    _write_project_context(tmp_path, "Devtrail", "배경")
    vault_tools.write_work_plan(
        project="Devtrail", goal="g", context_read="c", scope="s",
        approach="a", risks="r", session_id="sess-1", settings=_settings(tmp_path),
    )
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "## 리마인더" not in briefing.text


# ── briefing AgentMemory 우선순위 (사용 흐름 개선) ───────────────────────────


def _write_agent_memory(vault: Path, name: str, body: str, updated_at: str = "") -> None:
    meta = {"updated_at": updated_at} if updated_at else {}
    _write(vault, f"40_AgentMemory/{name}", body=body, **meta)


def test_briefing_memory_prefers_dynamic_files_over_profile(tmp_path):
    """긴 Profile이 있어도 OpenLoops/Lessons가 briefing 본문에 도달해야 한다.

    기존에는 7개 파일 전체 렌더를 앞 1200자에서 통째로 잘라, 목록 맨 앞의 정적인
    Profile이 예산을 다 쓰고 OpenLoops/Lessons는 어떤 세션에도 주입되지 못했다.
    """
    _write_project_context(tmp_path, "Devtrail", "배경")
    _write_agent_memory(tmp_path, "00_Profile.md", "프로필정적내용 " * 300)  # 1200자 초과
    _write_agent_memory(tmp_path, "01_CurrentFocus.md", "지금집중하는일 본문")
    _write_agent_memory(tmp_path, "05_OpenLoops.md", "미해결이슈 본문")
    _write_agent_memory(tmp_path, "06_Lessons.md", "일하는방식교훈 본문")

    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "지금집중하는일 본문" in briefing.text
    assert "미해결이슈 본문" in briefing.text
    assert "일하는방식교훈 본문" in briefing.text
    # 정적인 Profile 본문은 주입하지 않는다 — 참고 노트(read_note) 목록으로만 안내
    assert "프로필정적내용" not in briefing.text
    assert "40_AgentMemory/00_Profile.md" in briefing.source_refs


def test_briefing_memory_applies_per_file_budget(tmp_path):
    """한 파일이 길어도 다음 우선순위 파일이 잘려나가면 안 된다."""
    _write_project_context(tmp_path, "Devtrail", "배경")
    _write_agent_memory(tmp_path, "01_CurrentFocus.md", "포커스 " * 400)  # 700자 초과
    _write_agent_memory(tmp_path, "05_OpenLoops.md", "오픈루프핵심줄")

    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "오픈루프핵심줄" in briefing.text


def test_briefing_warns_on_stale_agent_memory(tmp_path):
    _write_project_context(tmp_path, "Devtrail", "배경")
    _write_agent_memory(tmp_path, "01_CurrentFocus.md", "오래된 포커스", updated_at="2026-01-01")
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "AgentMemory 신선도 경고" in briefing.text


def test_briefing_no_memory_warning_when_fresh(tmp_path):
    from datetime import datetime

    _write_project_context(tmp_path, "Devtrail", "배경")
    today = datetime.now().strftime("%Y-%m-%d")
    _write_agent_memory(tmp_path, "01_CurrentFocus.md", "신선한 포커스", updated_at=today)
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "AgentMemory 신선도 경고" not in briefing.text


# ── briefing Recent Decisions에 승격본 포함 (사용 흐름 개선) ─────────────────


def test_briefing_includes_promoted_decisions(tmp_path):
    """promote 후에도 결정이 briefing에서 사라지면 안 된다.

    기존에는 60_Candidates/Decisions만 읽어, 검토를 성실히 할수록(promote할수록)
    다음 세션 briefing에서 결정 이력이 사라졌다.
    """
    _write_project_context(tmp_path, "Devtrail", "배경")
    _write(tmp_path, "30_Projects/Devtrail/Decisions/캐시-전략-결정.md", body="결정 본문", title="캐시 전략 결정")

    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "Recent Decisions" in briefing.text
    assert "캐시 전략 결정" in briefing.text
    assert "30_Projects/Devtrail/Decisions/캐시-전략-결정.md" in briefing.source_refs


def test_briefing_tags_candidate_decisions_as_pending(tmp_path):
    _write_project_context(tmp_path, "Devtrail", "배경")
    _write(tmp_path, "60_Candidates/Decisions/미검토-결정.md", body="후보 본문", title="미검토 결정", project="Devtrail")

    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "미검토 결정" in briefing.text
    assert "검토 대기" in briefing.text


# ── 같은 세션 재기록 = 갱신 (산출물 품질 개선) ───────────────────────────────


def test_write_work_plan_same_session_updates_in_place(tmp_path):
    """같은 session_id로 Plan을 다시 쓰면 '(2)' 파일 대신 기존 파일을 갱신한다."""
    settings = _settings(tmp_path)
    r1 = vault_tools.write_work_plan(
        project="Devtrail", goal="1차 목표", context_read="c", scope="s",
        approach="a", risks="r", session_id="sess-up", settings=settings,
    )
    r2 = vault_tools.write_work_plan(
        project="Devtrail", goal="수정된 목표", context_read="c", scope="s",
        approach="a", risks="r", session_id="sess-up", settings=settings,
    )
    assert r1.rel_path == r2.rel_path
    content = (tmp_path / r2.rel_path).read_text(encoding="utf-8")
    assert "수정된 목표" in content
    assert "1차 목표" not in content


def test_write_work_plan_different_session_creates_new_file(tmp_path):
    settings = _settings(tmp_path)
    r1 = vault_tools.write_work_plan(
        project="Devtrail", goal="g1", context_read="c", scope="s",
        approach="a", risks="r", session_id="sess-a", settings=settings,
    )
    r2 = vault_tools.write_work_plan(
        project="Devtrail", goal="g2", context_read="c", scope="s",
        approach="a", risks="r", session_id="sess-b", settings=settings,
    )
    assert r1.rel_path != r2.rel_path


def test_write_session_process_rewrite_updates_process_and_worklog(tmp_path):
    """Process 재기록은 handoff와 워크로그를 모두 갱신한다 — 중간 스냅샷 방지.

    이 시나리오는 실제로 발생했다: 00:55 기록 후 머지·긴급수정이 이어졌는데
    기록엔 없어서, 다음 세션 briefing이 이미 끝난 Next Session 항목을 지시했다.
    """
    settings = _settings(tmp_path)
    r1 = vault_tools.write_session_process(
        project="Devtrail", what_changed="1차 작업", files_touched="a.py",
        project_decisions={}, implementation_trace="x", agent_execution_notes={},
        docs_update_candidates="", next_session="PR 머지하기", learning_recovery={},
        session_id="sess-rw", settings=settings,
    )
    r2 = vault_tools.write_session_process(
        project="Devtrail", what_changed="1차 작업 + 머지 + 긴급수정", files_touched="a.py, b.py",
        project_decisions={}, implementation_trace="x", agent_execution_notes={},
        docs_update_candidates="", next_session="훅 실세션 검증", learning_recovery={},
        session_id="sess-rw", settings=settings,
    )
    # handoff: 같은 파일 갱신
    assert r1.process.rel_path == r2.process.rel_path
    handoff = (tmp_path / r2.process.rel_path).read_text(encoding="utf-8")
    assert "긴급수정" in handoff
    assert "PR 머지하기" not in handoff
    # 워크로그: 같은 파일 갱신 (session-2.md가 생기면 안 됨)
    assert r1.worklog_rel_path == r2.worklog_rel_path
    worklog = (tmp_path / r2.worklog_rel_path).read_text(encoding="utf-8")
    assert "긴급수정" in worklog
    sessions = list((tmp_path / "10_Worklog" / "Sessions").glob("*.md"))
    assert len(sessions) == 1


def test_excerpt_orders_next_session_first(tmp_path):
    """handoff excerpt는 문서 순서가 아니라 Next Session 우선이어야 한다.

    excerpt는 400자에서 잘리므로, What Changed가 길면 다음 세션에 가장 필요한
    Next Session이 통째로 사멸했다.
    """
    settings = _settings(tmp_path)
    vault_tools.write_session_process(
        project="Devtrail", what_changed="아주 긴 변경 내역 " * 60, files_touched="a.py",
        project_decisions={}, implementation_trace="x", agent_execution_notes={},
        docs_update_candidates="", next_session="남은일-마커-9163", learning_recovery={},
        session_id="sess-ex", settings=settings,
    )
    briefing = vault_tools.get_project_briefing("Devtrail", settings=settings)
    assert "남은일-마커-9163" in briefing.text


def test_briefing_shows_tail_of_long_append_memory(tmp_path):
    """append형 파일(Lessons)은 길어지면 tail(최신)이 남아야 한다."""
    _write_project_context(tmp_path, "Devtrail", "배경")
    old_lessons = "- 오래된 교훈\n" * 100
    _write_agent_memory(tmp_path, "06_Lessons.md", old_lessons + "- 최신교훈-마커-3377")
    briefing = vault_tools.get_project_briefing("Devtrail", settings=_settings(tmp_path))
    assert "최신교훈-마커-3377" in briefing.text


def test_candidate_summary_autofilled_from_body(tmp_path):
    """summary를 안 넘겨도 본문 첫 의미 줄로 채워진다."""
    settings = _settings(tmp_path)
    result = vault_tools.record_note(
        "knowledge", "요약 자동화 테스트", "## 배경\n\n- RAG 인덱스는 야간에 재구축한다\n", settings=settings,
    )
    post = frontmatter.loads((tmp_path / result.rel_path).read_text(encoding="utf-8"))
    assert "RAG 인덱스는 야간에 재구축한다" in str(post.metadata.get("summary"))


def test_record_agent_improvement_truncates_long_title(tmp_path):
    """issue 전문이 길어도 제목(=파일명)은 상한이 있어야 한다 (Windows 260자 경로)."""
    settings = _settings(tmp_path)
    long_issue = "아주 긴 이슈 설명 " * 30
    result = vault_tools.record_agent_improvement(
        "Devtrail", long_issue, "개선 방법", settings=settings,
    )
    filename = result.rel_path.rsplit("/", 1)[-1]
    assert len(filename) < 100
    # 전문은 본문에 남는다
    content = (tmp_path / result.rel_path).read_text(encoding="utf-8")
    assert long_issue.strip() in content
