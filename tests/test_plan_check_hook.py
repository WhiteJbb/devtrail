"""PreToolUse plan-check 훅의 판정 로직을 검증한다."""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.services.session_markers import marker_path, write_json_atomic

_HOOK_PATH = Path(__file__).parent.parent / "scripts" / "hooks" / "plan-check.py"
spec = importlib.util.spec_from_file_location("plan_check_hook", _HOOK_PATH)
plan_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_check)


def _marker(
    tmp_path: Path,
    plan_written: bool,
    updated_at: datetime | None = None,
    session_id: str = "sess-x",
    pid: int | None = None,
) -> None:
    path = marker_path(tmp_path, session_id)
    now = updated_at or datetime.now()
    write_json_atomic(path, {
        "session_id": session_id,
        "repo_root": str(tmp_path.resolve()),
        "pid": pid or os.getpid(),
        "process_started_at": now.isoformat(),
        "process_written": False,
        "plan_written": plan_written,
        "updated_at": now.isoformat(),
    })


def _payload(tmp_path: Path, rel_file: str, tool: str = "Edit") -> dict:
    return {
        "tool_name": tool,
        "cwd": str(tmp_path),
        "tool_input": {"file_path": str(tmp_path / rel_file)},
    }


def test_denies_code_edit_without_plan(tmp_path):
    _marker(tmp_path, plan_written=False)
    out = plan_check.decide(_payload(tmp_path, "app/cli.py"))
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "write_work_plan" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_allows_after_plan_written(tmp_path):
    _marker(tmp_path, plan_written=True)
    assert plan_check.decide(_payload(tmp_path, "app/cli.py")) is None


def test_ambiguous_live_mcp_sessions_fail_open(tmp_path):
    _marker(tmp_path, plan_written=False, session_id="session-a")
    _marker(tmp_path, plan_written=False, session_id="session-b")
    assert plan_check.decide(_payload(tmp_path, "app/cli.py")) is None


@pytest.mark.parametrize("rel_file", [
    "README.md",
    "docs/guide.md",
    ".claude/global.md",
])
def test_allows_non_code_paths(tmp_path, rel_file):
    _marker(tmp_path, plan_written=False)
    assert plan_check.decide(_payload(tmp_path, rel_file)) is None


def test_denies_prompt_md_under_app(tmp_path):
    _marker(tmp_path, plan_written=False)
    assert plan_check.decide(_payload(tmp_path, "app/prompts/distill_candidates.md")) is not None


def test_allows_file_outside_repo(tmp_path):
    _marker(tmp_path, plan_written=False)
    payload = _payload(tmp_path, "app/cli.py")
    payload["tool_input"]["file_path"] = str(tmp_path.parent / "elsewhere" / "x.py")
    assert plan_check.decide(payload) is None


def test_allows_when_marker_absent(tmp_path):
    assert plan_check.decide(_payload(tmp_path, "app/cli.py")) is None


def test_allows_when_marker_stale(tmp_path):
    _marker(tmp_path, plan_written=False, updated_at=datetime.now() - timedelta(hours=13))
    assert plan_check.decide(_payload(tmp_path, "app/cli.py")) is None


def test_allows_when_marker_process_is_dead(tmp_path):
    _marker(tmp_path, plan_written=False, pid=2147483647)
    assert plan_check.decide(_payload(tmp_path, "app/cli.py")) is None


def test_ignores_non_edit_tools(tmp_path):
    _marker(tmp_path, plan_written=False)
    assert plan_check.decide(_payload(tmp_path, "app/cli.py", tool="Read")) is None


def test_root_python_file_is_code(tmp_path):
    _marker(tmp_path, plan_written=False)
    assert plan_check.decide(_payload(tmp_path, "dashboard.py")) is not None
