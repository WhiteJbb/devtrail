"""PreToolUse plan-check 훅(scripts/hooks/plan-check.py)의 판정 로직을 검증한다."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_HOOK_PATH = Path(__file__).parent.parent / "scripts" / "hooks" / "plan-check.py"

spec = importlib.util.spec_from_file_location("plan_check_hook", _HOOK_PATH)
plan_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_check)


def _marker(tmp_path, plan_written: bool, updated_at: datetime | None = None) -> None:
    marker_dir = tmp_path / ".claude" / ".vault-mcp"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / "current_session.json").write_text(
        json.dumps({
            "session_id": "sess-x",
            "process_written": False,
            "plan_written": plan_written,
            "updated_at": (updated_at or datetime.now()).isoformat(),
        }),
        encoding="utf-8",
    )


def _payload(tmp_path, rel_file: str, tool: str = "Edit") -> dict:
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


@pytest.mark.parametrize("rel_file", [
    "README.md",           # 문서는 Plan 불요
    "docs/guide.md",       # 코드 경로 밖
    ".claude/global.md",   # 설정/문서
])
def test_allows_non_code_paths(tmp_path, rel_file):
    _marker(tmp_path, plan_written=False)
    assert plan_check.decide(_payload(tmp_path, rel_file)) is None


def test_denies_prompt_md_under_app(tmp_path):
    """app/prompts/*.md는 동작을 바꾸는 구현이므로 코드 경로로 취급한다."""
    _marker(tmp_path, plan_written=False)
    assert plan_check.decide(_payload(tmp_path, "app/prompts/distill_candidates.md")) is not None


def test_allows_file_outside_repo(tmp_path):
    _marker(tmp_path, plan_written=False)
    payload = _payload(tmp_path, "app/cli.py")
    payload["tool_input"]["file_path"] = str(tmp_path.parent / "elsewhere" / "x.py")
    assert plan_check.decide(payload) is None


def test_allows_when_marker_absent(tmp_path):
    """마커 부재 = MCP 미연결 세션 — 강제하지 않는다."""
    assert plan_check.decide(_payload(tmp_path, "app/cli.py")) is None


def test_allows_when_marker_stale(tmp_path):
    """12시간 지난 마커는 이전 세션 잔존으로 간주한다."""
    _marker(tmp_path, plan_written=False, updated_at=datetime.now() - timedelta(hours=13))
    assert plan_check.decide(_payload(tmp_path, "app/cli.py")) is None


def test_ignores_non_edit_tools(tmp_path):
    _marker(tmp_path, plan_written=False)
    payload = _payload(tmp_path, "app/cli.py", tool="Read")
    assert plan_check.decide(payload) is None


def test_root_python_file_is_code(tmp_path):
    _marker(tmp_path, plan_written=False)
    assert plan_check.decide(_payload(tmp_path, "dashboard.py")) is not None
