"""Stop/PreCompact 훅의 세션 marker 판정을 검증한다."""

from __future__ import annotations

import importlib.util
import os
import json
from datetime import datetime
from pathlib import Path

import pytest

from app.services.session_markers import claude_session_path, marker_path, write_json_atomic

_HOOK_PATH = Path(__file__).parent.parent / "scripts" / "hooks" / "stop-process-check.py"
spec = importlib.util.spec_from_file_location("stop_process_hook", _HOOK_PATH)
stop_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stop_hook)


def _marker(tmp_path: Path, session_id: str, process_written: bool = False) -> None:
    now = datetime.now().isoformat()
    write_json_atomic(marker_path(tmp_path, session_id), {
        "session_id": session_id,
        "repo_root": str(tmp_path.resolve()),
        "pid": os.getpid(),
        "process_started_at": now,
        "process_written": process_written,
        "plan_written": False,
        "updated_at": now,
    })


def test_no_unique_marker_does_not_enforce(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(stop_hook, "_read_payload", lambda: {"cwd": str(tmp_path)})
    monkeypatch.setattr(stop_hook, "_git", lambda *args: pytest.fail("git should not run"))
    assert stop_hook.main() == 0
    assert capsys.readouterr().out == ""


def test_single_live_marker_enforces_process_record(tmp_path, monkeypatch, capsys):
    _marker(tmp_path, "session-a")
    monkeypatch.setattr(stop_hook, "_read_payload", lambda: {"cwd": str(tmp_path)})

    def fake_git(args, cwd):
        return " M app/file.py" if args[0] == "status" else None

    monkeypatch.setattr(stop_hook, "_git", fake_git)
    assert stop_hook.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "block"
    assert "write_session_process" in output["reason"]


def _session_start(tmp_path: Path, session_id: str) -> None:
    write_json_atomic(claude_session_path(tmp_path, session_id), {
        "session_id": session_id, "started_at": datetime.now().isoformat(),
    })


def test_session_start_marker_enforces_without_mcp_marker(tmp_path, monkeypatch, capsys):
    """MCP tool을 한 번도 안 부른 세션도 커밋이 있으면 기록을 요구한다."""
    _session_start(tmp_path, "claude-1")
    monkeypatch.setattr(stop_hook, "_read_payload", lambda: {"cwd": str(tmp_path), "session_id": "claude-1"})

    def fake_git(args, cwd):
        return "" if args[0] == "status" else "abc123"

    monkeypatch.setattr(stop_hook, "_git", fake_git)
    assert stop_hook.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["decision"] == "block"
    assert "write_session_process" in output["reason"]


def test_session_start_marker_passes_clean_session(tmp_path, monkeypatch, capsys):
    _session_start(tmp_path, "claude-1")
    monkeypatch.setattr(stop_hook, "_read_payload", lambda: {"cwd": str(tmp_path), "session_id": "claude-1"})
    monkeypatch.setattr(stop_hook, "_git", lambda *args: "")
    assert stop_hook.main() == 0
    assert capsys.readouterr().out == ""


def test_other_sessions_start_marker_is_ignored(tmp_path, monkeypatch, capsys):
    _session_start(tmp_path, "claude-other")
    monkeypatch.setattr(stop_hook, "_read_payload", lambda: {"cwd": str(tmp_path), "session_id": "claude-1"})
    monkeypatch.setattr(stop_hook, "_git", lambda *args: pytest.fail("git should not run"))
    assert stop_hook.main() == 0
    assert capsys.readouterr().out == ""


def test_ambiguous_live_markers_fail_open(tmp_path, monkeypatch, capsys):
    _marker(tmp_path, "session-a")
    _marker(tmp_path, "session-b")
    monkeypatch.setattr(stop_hook, "_read_payload", lambda: {"cwd": str(tmp_path)})
    monkeypatch.setattr(stop_hook, "_git", lambda *args: pytest.fail("git should not run"))
    assert stop_hook.main() == 0
    assert capsys.readouterr().out == ""
