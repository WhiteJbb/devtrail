"""SessionStart 훅이 다른 MCP 프로세스의 marker를 건드리지 않는지 검증한다."""

from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path

from app.services.session_markers import marker_path, write_json_atomic

_HOOK_PATH = Path(__file__).parent.parent / "scripts" / "hooks" / "session-start-briefing.py"
spec = importlib.util.spec_from_file_location("session_start_hook", _HOOK_PATH)
session_start_hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session_start_hook)


def test_session_start_preserves_live_mcp_marker(tmp_path, monkeypatch):
    path = marker_path(tmp_path, "other-session")
    now = datetime.now().isoformat()
    marker = {
        "session_id": "other-session",
        "repo_root": str(tmp_path.resolve()),
        "pid": os.getpid(),
        "process_started_at": now,
        "updated_at": now,
        "process_written": False,
        "plan_written": True,
    }
    write_json_atomic(path, marker)
    monkeypatch.setattr(session_start_hook, "_read_payload", lambda: {"cwd": str(tmp_path)})
    monkeypatch.setattr(session_start_hook, "_find_devtrail", lambda _: None)

    assert session_start_hook.main() == 0
    assert json.loads(path.read_text(encoding="utf-8")) == marker


def test_session_start_records_start_marker_once(tmp_path, monkeypatch):
    """Stop 훅 fallback용 시작 마커를 남기고, resume/compact 재시작에는 덮어쓰지 않는다."""
    from app.services.session_markers import claude_session_path

    payload = {"cwd": str(tmp_path), "session_id": "claude-1", "source": "startup"}
    monkeypatch.setattr(session_start_hook, "_read_payload", lambda: payload)
    monkeypatch.setattr(session_start_hook, "_find_devtrail", lambda _: None)

    assert session_start_hook.main() == 0
    path = claude_session_path(tmp_path, "claude-1")
    first = json.loads(path.read_text(encoding="utf-8"))
    assert first["session_id"] == "claude-1"
    datetime.fromisoformat(first["started_at"])

    monkeypatch.setattr(session_start_hook, "_read_payload", lambda: {**payload, "source": "compact"})
    assert session_start_hook.main() == 0
    assert json.loads(path.read_text(encoding="utf-8")) == first
