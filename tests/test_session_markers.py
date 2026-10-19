"""MCP session marker의 격리, liveness, atomic write를 검증한다."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from app.services import session_markers


def _write_marker(root: Path, session_id: str, pid: int | None = None, parent_pid: int = 0) -> Path:
    now = datetime.now().isoformat()
    path = session_markers.marker_path(root, session_id)
    session_markers.write_json_atomic(path, {
        "session_id": session_id,
        "repo_root": str(root.resolve()),
        "pid": pid or os.getpid(),
        "parent_pid": parent_pid,
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


def test_ancestor_pids_starts_with_self_and_includes_parent():
    chain = session_markers.ancestor_pids()
    assert chain[0] == os.getpid()
    assert os.getppid() in chain


def test_marker_for_current_session_picks_own_among_concurrent(tmp_path):
    """동시 세션 둘: 내 조상(여기선 내 ppid)을 parent_pid로 가진 마커만 골라야 한다."""
    _write_marker(tmp_path, "mine", parent_pid=os.getppid())
    _write_marker(tmp_path, "other", parent_pid=2147483000)
    picked = session_markers.live_mcp_marker_for_current_session(tmp_path)
    assert picked is not None and picked["session_id"] == "mine"
    assert session_markers.unique_live_mcp_marker(tmp_path) is None  # 기존 판정은 여전히 포기


def test_marker_for_current_session_falls_back_to_unique(tmp_path):
    _write_marker(tmp_path, "legacy")  # parent_pid 없음(구 마커) — 하나뿐이면 그대로 쓴다
    picked = session_markers.live_mcp_marker_for_current_session(tmp_path)
    assert picked is not None and picked["session_id"] == "legacy"
    _write_marker(tmp_path, "legacy-2")
    assert session_markers.live_mcp_marker_for_current_session(tmp_path) is None
