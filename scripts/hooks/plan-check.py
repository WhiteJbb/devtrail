"""Plan 기록 없이 코드 파일 수정을 시작할 때 Claude Code를 차단한다."""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.services.session_markers import unique_live_mcp_marker

_EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
_CODE_PREFIXES = ("app/", "tests/", "scripts/")


def _read_payload():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else None
    except Exception:
        return None


def decide(payload: dict) -> dict | None:
    """Plan 없이 코드 파일을 수정하려는 경우에만 deny 응답을 만든다."""
    if payload.get("tool_name") not in _EDIT_TOOLS:
        return None

    cwd = payload.get("cwd") or os.getcwd()
    tool_input = payload.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if not file_path:
        return None

    try:
        rel = Path(file_path).resolve().relative_to(Path(cwd).resolve())
    except (ValueError, OSError):
        return None
    rel_posix = rel.as_posix()
    is_code = rel_posix.startswith(_CODE_PREFIXES) or (
        len(rel.parts) == 1 and rel.suffix == ".py"
    )
    if not is_code:
        return None

    marker = unique_live_mcp_marker(Path(cwd))
    if marker is None or marker.get("plan_written"):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"코드 수정 전에 Plan을 기록해야 합니다 ({rel_posix} 수정 시도). "
                "write_work_plan(MCP)으로 이번 작업의 goal/context_read/scope/"
                "approach/risks를 먼저 기록한 뒤 다시 시도하세요."
            ),
        }
    }


def main() -> int:
    payload = _read_payload()
    if not isinstance(payload, dict):
        return 0
    output = decide(payload)
    if output is not None:
        sys.stdout.buffer.write(json.dumps(output).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
