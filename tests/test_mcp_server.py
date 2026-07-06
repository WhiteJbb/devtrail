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


def test_registers_seven_canonical_tools(vault_env, monkeypatch):
    mod = _reload_mcp_server(vault_env, monkeypatch)
    tools = {t.name for t in mod.mcp._tool_manager.list_tools()}
    assert tools == {
        "get_project_briefing",
        "search_vault",
        "read_note",
        "record_note",
        "record_agent_improvement",
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


def test_write_session_process_updates_marker_file(vault_env, monkeypatch):
    mod = _reload_mcp_server(vault_env, monkeypatch)
    write_session_process = mod.mcp._tool_manager.get_tool("write_session_process").fn

    marker_path = mod._session_marker_path()
    assert marker_path.exists()
    import json

    before = json.loads(marker_path.read_text(encoding="utf-8"))
    assert before["process_written"] is False

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
