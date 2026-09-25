"""SessionStart에서 devtrail briefing을 Claude Code context로 전달한다."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


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


def main() -> int:
    payload = _read_payload()
    cwd = payload.get("cwd") if isinstance(payload, dict) and payload.get("cwd") else os.getcwd()
    repo_root = Path(__file__).resolve().parents[2]
    exe = _find_devtrail(repo_root)
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
