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
        wiki_folder="60_Wiki",
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
        agent_execution_notes={"mistakes": "경로를 잘못 짚음", "evidence": "로그 확인", "confidence": "high"},
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


def test_get_project_briefing_matches_registered_project(tmp_path):
    _write(tmp_path, "30_Projects/Devtrail/Context.md", body="Devtrail 프로젝트 컨텍스트 본문")
    settings = _settings(tmp_path)
    briefing = vault_tools.get_project_briefing("Devtrail", settings=settings)
    assert briefing.matched is True
    assert briefing.project == "Devtrail"
    assert "Devtrail 프로젝트 컨텍스트 본문" in briefing.text


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
