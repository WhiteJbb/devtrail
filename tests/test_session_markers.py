"""MCP session marker의 격리, liveness, atomic write를 검증한다."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from app.services import session_markers


def _write_marker(root: Path, session_id: str, pid: int | None = None) -> Path:
    now = datetime.now().isoformat()
    path = session_markers.marker_path(root, session_id)
    session_markers.write_json_atomic(path, {
        "session_id": session_id,
        "repo_root": str(root.resolve()),
        "pid": pid or os.getpid(),
        "process_started_at": now,
        "updated_at": now,
        "process_written": False,
        "plan_written": False,
    })
    return path


def test_marker_paths_are_per_session_and_hide_raw_id(tmp_path):
    first = session_markers.marker_path(tmp_path, "session-a")
    second = session_markers.marker_path(tmp_path, "session-b")
    assert first != second
    assert "session-a" not in str(first)
    assert "session-b" not in str(second)


def test_unique_live_marker_rejects_multiple_processes(tmp_path):
    _write_marker(tmp_path, "session-a")
    _write_marker(tmp_path, "session-b")
    assert session_markers.unique_live_mcp_marker(tmp_path) is None


def test_dead_process_marker_is_not_live(tmp_path):
    _write_marker(tmp_path, "dead-session", pid=2147483647)
    assert session_markers.unique_live_mcp_marker(tmp_path) is None


def test_atomic_write_failure_preserves_old_marker(tmp_path, monkeypatch):
    path = _write_marker(tmp_path, "session-a")
    old = json.loads(path.read_text(encoding="utf-8"))

    def partial_then_fail(data, stream, **kwargs):
        stream.write('{"partial":')
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(session_markers.json, "dump", partial_then_fail)
    with pytest.raises(OSError, match="interrupted"):
        session_markers.write_json_atomic(path, {"plan_written": True})

    assert json.loads(path.read_text(encoding="utf-8")) == old
    assert list(path.parent.glob("*.tmp")) == []
