"""SessionStart에서 devtrail briefing을 Claude Code context로 전달한다."""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from app.services.session_markers import claude_session_path, write_json_atomic


def _read_payload():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else None
    except Exception:
        return None


def _find_devtrail(repo_root: Path):
    exe = shutil.which("devtrail")
    if exe:
        return exe
    for candidate in (repo_root / ".venv/bin/devtrail", repo_root / ".venv/Scripts/devtrail.exe"):
        if candidate.exists():
            return str(candidate)
    return None


def _record_session_start(cwd: str, session_id: str) -> None:
    """Stop 훅이 MCP 마커 없이도 세션 시작 시각을 알 수 있게 남긴다.

    resume/compact로 같은 세션이 다시 시작돼도 처음 시각을 보존한다 — 덮어쓰면
    컴팩팅 전 커밋이 판정에서 빠진다.
    """
    path = claude_session_path(Path(cwd), session_id)
    if path.exists():
        return
    try:
        write_json_atomic(path, {"session_id": session_id, "started_at": datetime.now().isoformat()})
    except OSError:
        pass


def main() -> int:
    payload = _read_payload()
    if not isinstance(payload, dict):
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()
    if payload.get("session_id"):
        _record_session_start(cwd, str(payload["session_id"]))
    exe = _find_devtrail(REPO_ROOT)
    if not exe:
        return 0

    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        proc = subprocess.run(
            [exe, "project-briefing", cwd],
            capture_output=True,
            timeout=25,
            env=env,
        )
    except Exception:
        return 0
    if proc.returncode != 0:
        return 0
    briefing = proc.stdout.decode("utf-8", errors="replace").strip()
    if briefing:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": briefing,
            }
        }
        sys.stdout.buffer.write(json.dumps(output).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
