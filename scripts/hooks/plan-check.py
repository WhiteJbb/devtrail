"""Claude Code PreToolUse 훅 — Plan 없이 코드 수정을 시작하면 차단한다.

scripts/hooks/run-hook.sh가 OS에 맞는 python으로 실행하는 크로스플랫폼 구현.

CLAUDE.md의 "구현 전에 반드시 Plan을 남긴다" 규칙은 에이전트의 자율 준수에만
의존하면 누락된다(2026-07-08 세션이 작업 5묶음을 Plan 없이 진행). Stop 훅이
Process를 강제하듯, 이 훅은 Edit/Write가 코드 경로를 건드리는 순간 세션 마커의
plan_written을 검사해 write_work_plan 선행 호출을 강제한다.

통과 조건(과차단 방지):
- 대상 tool(Edit/Write/NotebookEdit)이 아니거나 파일 경로가 없음
- 파일이 repo 밖(scratchpad, vault, 메모리 등)이거나 코드 경로가 아님
  (코드 경로: app/, tests/, scripts/, 루트 *.py — 문서·설정은 Plan 불요)
- 마커 부재/stale(12h) — MCP 미연결 fallback 세션은 강제하지 않는다
  (SessionStart 훅이 세션 시작 시 이전 마커를 지우므로, 마커 존재 = 이번 세션에
  MCP가 연결됐다는 뜻)
- plan_written=true — write_work_plan이 이미 호출됨
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

_EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
_CODE_PREFIXES = ("app/", "tests/", "scripts/")


def _read_payload():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else None
    except Exception:
        return None


def decide(payload: dict) -> dict | None:
    """차단이 필요하면 PreToolUse deny 출력 dict를, 통과면 None을 반환한다."""
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
        return None  # repo 밖 파일은 이 규칙의 대상이 아니다
    rel_posix = rel.as_posix()
    is_code = rel_posix.startswith(_CODE_PREFIXES) or (
        len(rel.parts) == 1 and rel.suffix == ".py"
    )
    if not is_code:
        return None

    marker_path = Path(cwd) / ".claude" / ".vault-mcp" / "current_session.json"
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        updated_at = datetime.fromisoformat(str(marker["updated_at"]))
        now = datetime.now(updated_at.tzinfo) if updated_at.tzinfo else datetime.now()
        if now - updated_at >= timedelta(hours=12):
            return None  # 이전 세션의 잔존 마커
        if marker.get("plan_written"):
            return None
    except Exception:
        return None  # 마커 부재/파손 = MCP 미연결 — 강제하지 않는다

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"구현 전 Plan이 기록되지 않았습니다 ({rel_posix} 수정 시도). "
                "write_work_plan(MCP)으로 이번 작업의 goal/context_read/scope/"
                "approach/risks를 먼저 기록한 뒤 다시 시도하세요 — 기록하면 이 "
                "세션에서는 다시 차단되지 않습니다."
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
