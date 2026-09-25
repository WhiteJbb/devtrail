"""Process 기록 없이 작업한 MCP 세션의 종료를 막는다."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.services.session_markers import unique_live_mcp_marker


def _read_payload():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else None
    except Exception:
        return None


def _emit_block(reason: str) -> None:
    sys.stdout.buffer.write(json.dumps({"decision": "block", "reason": reason}).encode("utf-8"))


def _git(args, cwd):
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=15)
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        return None


def main() -> int:
    payload = _read_payload()
    if not isinstance(payload, dict):
        payload = {}
    if payload.get("stop_hook_active"):
        return 0

    cwd = payload.get("cwd") or os.getcwd()
    marker = unique_live_mcp_marker(Path(cwd))
    if marker is None:
        return 0
    process_written = bool(marker.get("process_written"))
    try:
        session_started_at = datetime.fromisoformat(str(marker["updated_at"]))
    except (KeyError, TypeError, ValueError):
        return 0

    git_status = _git(["status", "--porcelain"], cwd)
    since = session_started_at.strftime("%Y-%m-%dT%H:%M:%S")
    session_commits = _git(["log", "--since", since, "-1", "--format=%H"], cwd)

    if process_written:
        if session_commits:
            _emit_block(
                "write_session_process 기록 이후에 새 커밋이 생겼습니다. 이후 작업을 반영해 "
                "write_session_process를 다시 호출하세요 (같은 세션 기록이 갱신됩니다)."
            )
        return 0

    if not git_status and not session_commits:
        return 0
    if session_commits and not git_status:
        reason = (
            "이번 세션에서 커밋이 만들어졌는데 write_session_process가 호출되지 않았습니다. "
            "세션을 마치기 전에 write_session_process로 Process를 남기세요."
        )
    else:
        reason = (
            "git 작업 디렉터리에 변경이 있는데 이번 세션의 write_session_process가 "
            "호출되지 않았습니다. 세션을 마치기 전에 Process를 남기세요."
        )
    _emit_block(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
