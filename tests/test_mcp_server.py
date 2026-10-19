"""MCP 서버(app/mcp_server.py) tool 등록과 session_id 자동 주입을 검증한다."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings


@pytest.fixture()
def vault_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "")
    monkeypatch.setenv("MESSENGER_PROVIDER", "")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _reload_mcp_server(tmp_path, monkeypatch):
    """모듈을 새로 import해 매 테스트마다 독립된 session_id/마커 경로를 쓰게 한다."""
    import sys

    monkeypatch.chdir(tmp_path)
    sys.modules.pop("app.mcp_server", None)
    import app.mcp_server as mcp_server_module

    return mcp_server_module


def test_registers_canonical_tools(vault_env, monkeypatch):
    mod = _reload_mcp_server(vault_env, monkeypatch)
    tools = {t.name for t in mod.mcp._tool_manager.list_tools()}
    assert tools == {
        "get_project_briefing",
        "search_vault",
        "read_note",
        "get_recent_sessions",
        "get_decisions",
        "get_known_problems",
        "record_note",
        "record_problem",
        "record_agent_improvement",
        "update_open_loops",
        "write_work_plan",
        "write_session_process",
    }


def test_write_work_plan_auto_injects_session_id(vault_env, monkeypatch):
    mod = _reload_mcp_server(vault_env, monkeypatch)
    write_work_plan = mod.mcp._tool_manager.get_tool("write_work_plan").fn

    result = write_work_plan(
        project="Devtrail", goal="목표", context_read="컨텍스트", scope="범위", approach="접근", risks="위험"
    )
    assert "SessionHandoffs/Devtrail" in result["rel_path"]

    import frontmatter

    post = frontmatter.loads((vault_env / result["rel_path"]).read_text(encoding="utf-8"))
    assert post.metadata["session_id"] == mod._SESSION_ID


def test_import_does_not_create_marker_file(vault_env, monkeypatch):
    """모듈 import만으로는 마커가 생기면 안 된다(P4.1).

    import 시점에 마커를 쓰면 REPL이나 향후 eager import 시 라이브 세션의 진짜
    마커를 덮어쓸 수 있다.
    """
    mod = _reload_mcp_server(vault_env, monkeypatch)
    assert not mod._session_marker_path().exists()


def test_server_start_does_not_create_marker_file(vault_env, monkeypatch):
    """서버 기동만으로 마커가 생기면 안 된다 — `claude mcp list` 헬스체크 때문이다.

    헬스체크는 서버를 띄웠다 즉시 닫는데, 그 탐침이 마커를 남기면 plan-check 훅이
    "이번 세션에 MCP가 연결됐다"로 읽는다. MCP tool이 없는 세션은 write_work_plan을
    호출할 수단이 없으므로 12시간 동안 코드 수정이 막힌다(2026-09-07 실제 발생).
    """
    mod = _reload_mcp_server(vault_env, monkeypatch)
    monkeypatch.setattr(mod.mcp, "run", lambda **kwargs: None)

    mod.main()

    assert not mod._session_marker_path().exists()


def test_first_tool_call_creates_marker_file(vault_env, monkeypatch):
    """탐침과 라이브 세션을 가르는 신호는 'tool을 실제로 호출했는가'다."""
    import json

    mod = _reload_mcp_server(vault_env, monkeypatch)
    assert not mod._session_marker_path().exists()

    mod.mcp._tool_manager.get_tool("search_vault").fn(query="아무거나")

    marker = json.loads(mod._session_marker_path().read_text(encoding="utf-8"))
    assert marker["session_id"] == mod._SESSION_ID
    assert marker["plan_written"] is False
    assert marker["process_written"] is False
    assert marker["pid"]
    assert marker["repo_root"] == str(vault_env.resolve())


def test_mcp_processes_keep_separate_markers(vault_env, monkeypatch):
    import json

    first = _reload_mcp_server(vault_env, monkeypatch)
    first._write_session_marker(plan_written=True)
    first_path = first._session_marker_path()

    second = _reload_mcp_server(vault_env, monkeypatch)
    second._write_session_marker(plan_written=False)
    second_path = second._session_marker_path()

    assert first_path != second_path
    assert json.loads(first_path.read_text(encoding="utf-8"))["plan_written"] is True
    assert json.loads(second_path.read_text(encoding="utf-8"))["plan_written"] is False


def test_write_session_process_updates_marker_file(vault_env, monkeypatch):
    mod = _reload_mcp_server(vault_env, monkeypatch)
    write_session_process = mod.mcp._tool_manager.get_tool("write_session_process").fn

    # main()이 서버 시작 시 쓰는 초기 마커를 직접 재현한다(mcp.run은 블로킹이라 테스트에서
    # 호출할 수 없다).
    mod._write_session_marker(process_written=False)

    marker_path = mod._session_marker_path()
    assert marker_path.exists()
    import json

    before = json.loads(marker_path.read_text(encoding="utf-8"))
    assert before["process_written"] is False
    assert "updated_at" in before

    write_session_process(
        project="Devtrail",
        what_changed="변경",
        files_touched="파일",
        project_decisions={},
        implementation_trace="흐름",
        agent_execution_notes={},
        docs_update_candidates="",
        next_session="",
        learning_recovery={},
    )

    after = json.loads(marker_path.read_text(encoding="utf-8"))
    assert after["process_written"] is True
    assert after["session_id"] == mod._SESSION_ID


def test_write_work_plan_sets_plan_written_marker(vault_env, monkeypatch):
    """write_work_plan은 마커에 plan_written=True를 기록해야 한다.

    PreToolUse 훅(plan-check)이 이 값을 읽어 Plan 없는 코드 수정을 차단한다 —
    값이 안 쓰이면 훅이 Plan을 이미 남긴 세션까지 계속 차단한다.
    """
    import json

    mod = _reload_mcp_server(vault_env, monkeypatch)
    mod._write_session_marker(process_written=False, plan_written=False)

    write_work_plan = mod.mcp._tool_manager.get_tool("write_work_plan").fn
    write_work_plan(
        project="Devtrail", goal="목표", context_read="컨텍스트", scope="범위", approach="접근", risks="위험"
    )

    marker = json.loads(mod._session_marker_path().read_text(encoding="utf-8"))
    assert marker["plan_written"] is True
    assert marker["process_written"] is False  # 다른 필드는 보존


def test_write_session_process_preserves_plan_written(vault_env, monkeypatch):
    """Process 기록이 마커를 갱신할 때 plan_written을 잃으면 안 된다.

    잃으면 Process 기록 직후의 후속 코드 수정이 plan-check 훅에 다시 차단된다.
    """
    import json

    mod = _reload_mcp_server(vault_env, monkeypatch)
    mod._write_session_marker(process_written=False, plan_written=True)

    write_session_process = mod.mcp._tool_manager.get_tool("write_session_process").fn
    write_session_process(
        project="Devtrail", what_changed="변경", files_touched="파일", project_decisions={},
        implementation_trace="흐름", agent_execution_notes={}, docs_update_candidates="",
        next_session="", learning_recovery={},
    )

    marker = json.loads(mod._session_marker_path().read_text(encoding="utf-8"))
    assert marker["process_written"] is True
    assert marker["plan_written"] is True


def test_record_note_returns_plain_dict(vault_env, monkeypatch):
    mod = _reload_mcp_server(vault_env, monkeypatch)
    record_note = mod.mcp._tool_manager.get_tool("record_note").fn
    result = record_note(kind="knowledge", title="테스트 지식", body="본문")
    assert result["rel_path"].startswith("60_Candidates/Knowledge/")


def test_search_vault_returns_list_of_dicts(vault_env, monkeypatch):
    mod = _reload_mcp_server(vault_env, monkeypatch)
    record_note = mod.mcp._tool_manager.get_tool("record_note").fn
    record_note(kind="knowledge", title="검색용노트", body="고유검색어123 포함")

    search_vault = mod.mcp._tool_manager.get_tool("search_vault").fn
    hits = search_vault(query="고유검색어123", limit=5)
    assert isinstance(hits, list)
    assert hits[0]["status"] == "candidate"


def test_get_project_briefing_returns_dict_with_matched_field(vault_env, monkeypatch):
    mod = _reload_mcp_server(vault_env, monkeypatch)
    get_project_briefing = mod.mcp._tool_manager.get_tool("get_project_briefing").fn
    result = get_project_briefing(project_or_repo="없는프로젝트이름")
    assert result["matched"] is False
    assert "candidates" in result


def test_write_tools_warn_on_suspicious_hangul(vault_env, monkeypatch):
    """모델이 유니코드 이스케이프를 틀려 생긴 음절(등급 → 뒱급)을 기록 시점에 되돌려 준다."""
    mod = _reload_mcp_server(vault_env, monkeypatch)
    write_session_process = mod.mcp._tool_manager.get_tool("write_session_process").fn

    clean = write_session_process(project="Devtrail", what_changed="경고 등급을 내렸다")
    assert "warnings" not in clean

    corrupted = write_session_process(
        project="Devtrail",
        what_changed="경고 뒱급을 내렸다",
        agent_execution_notes={"next_checks": "예삸를 먼저 확인"},
    )
    assert "뒱급을" in corrupted["warnings"][0]
    assert "예삸를" in corrupted["warnings"][0]
    assert corrupted["process"]["rel_path"]



def test_write_session_process_warns_on_blank_learning_recovery(vault_env, monkeypatch):
    """빈 틀("- ", "1. ")만 넘긴 Learning Recovery는 복습 질문이 안 생기므로 경고로 돌려준다."""
    mod = _reload_mcp_server(vault_env, monkeypatch)
    write_session_process = mod.mcp._tool_manager.get_tool("write_session_process").fn

    blank = write_session_process(
        project="Devtrail", what_changed="1. 작업",
        learning_recovery={"ai_led": "- ", "unclear_concepts": "- ", "questions": "1. ", "related_candidates": "-"},
    )
    assert any("learning_recovery" in w for w in blank["warnings"])

    filled = write_session_process(
        project="Devtrail", what_changed="2. 작업", append_to=["what_changed"],
        learning_recovery={"ai_led": "토큰 선택", "unclear_concepts": "", "questions": "왜 fontsource인가", "related_candidates": ""},
    )
    assert "warnings" not in filled

    omitted = write_session_process(project="Devtrail", what_changed="3. 작업", append_to=["what_changed"])
    assert "warnings" not in omitted


def test_update_open_loops_tool_edits_vault_file(vault_env, monkeypatch):
    mod = _reload_mcp_server(vault_env, monkeypatch)
    update_open_loops = mod.mcp._tool_manager.get_tool("update_open_loops").fn
    result = update_open_loops(project="Devtrail", add=["Stop 훅 fallback 실효 확인 (#78)"], section="실효 확인")
    assert result["added"] and result["resolved"] == [] and "warnings" not in result
    assert "Stop 훅 fallback" in (vault_env / "40_AgentMemory" / "05_OpenLoops.md").read_text(encoding="utf-8")


def test_server_instructions_name_read_tools(vault_env, monkeypatch):
    """서버 instructions는 클라이언트 시스템 프롬프트에 주입된다 — 읽기 도구 트리거가 들어 있어야 한다."""
    mod = _reload_mcp_server(vault_env, monkeypatch)
    text = mod.mcp.instructions or ""
    for name in ("get_known_problems", "get_decisions", "search_vault", "get_recent_sessions"):
        assert name in text


def test_tool_calls_import_no_new_app_modules(vault_env, monkeypatch):
    """MCP tool 경로에 지연 import가 없어야 한다.

    MCP 서버는 세션 내내 살아 있는데 update-devtrail이 10분마다 main을 pull한다. tool이
    함수 안에서 처음 import하는 모듈은 디스크의 새 코드를 읽으므로, 삭제·개명된 모듈이면
    "No module named ..."로 터진다(2026-07-09, 2026-10-18 rpg-game-web·devtrail 세션 실제 발생).
    기동 시 다 import해 두면 구서버도 자기 스냅샷으로 끝까지 동작한다.
    """
    import sys

    mod = _reload_mcp_server(vault_env, monkeypatch)
    before = {m for m in sys.modules if m.startswith("app.")}
    tools = mod.mcp._tool_manager
    tools.get_tool("get_project_briefing").fn("Devtrail")
    tools.get_tool("search_vault").fn("x")
    tools.get_tool("get_recent_sessions").fn("Devtrail")
    tools.get_tool("get_decisions").fn("Devtrail")
    tools.get_tool("get_known_problems").fn("Devtrail")
    tools.get_tool("record_note").fn("knowledge", "t", "b", "Devtrail")
    tools.get_tool("record_problem").fn(
        project="Devtrail", title="t", symptoms="s", cause="c", solution="x", prevention="p"
    )
    tools.get_tool("record_agent_improvement").fn("Devtrail", "i", "m")
    tools.get_tool("update_open_loops").fn(project="Devtrail", add=["a"])
    tools.get_tool("write_work_plan").fn("Devtrail", "g", "c", "s", "a", "r")
    for _ in range(2):  # 두 번째 호출은 기존 노트 갱신 경로를 탄다
        tools.get_tool("write_session_process").fn(
            project="Devtrail",
            what_changed="변경",
            files_touched="파일",
            project_decisions={"decision": "d", "reason": "r"},
            implementation_trace="흐름",
            agent_execution_notes={"scope": "project", "better_approach": "b"},
            docs_update_candidates="",
            next_session="n",
            learning_recovery={"ai_led": "a"},
        )
    with pytest.raises(ValueError):
        tools.get_tool("read_note").fn("00_Inbox/x.md")
    after = {m for m in sys.modules if m.startswith("app.")}
    assert after - before == set()
