"""Claude Code SessionStart 훅 — devtrail project-briefing을 additionalContext로 주입한다.

scripts/hooks/run-hook.sh가 OS에 맞는 python으로 실행하는 크로스플랫폼 구현.
(기존 scripts/windows/hooks/session-start-briefing.ps1의 포트 — ps1은 참고용으로 유지)

devtrail 부재/실패는 조용히 건너뛴다 — SessionStart 훅은 세션 진행을 막아서는 안 된다.
"""

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
    for cand in (repo_root / ".venv/bin/devtrail", repo_root / ".venv/Scripts/devtrail.exe"):
        if cand.exists():
            return str(cand)
    return None


def main() -> int:
    payload = _read_payload()
    cwd = payload.get("cwd") if isinstance(payload, dict) and payload.get("cwd") else os.getcwd()

    # 세션마다 clean start — 이전 세션이 남긴 마커가 이번 세션의 것으로 오인되지 않게
    # 지운다. MCP 서버(devtrail mcp-serve)가 시작되면 main()이 새 마커를 쓴다.
    marker = Path(cwd) / ".claude" / ".vault-mcp" / "current_session.json"
    try:
        marker.unlink()
    except OSError:
        pass

    repo_root = Path(__file__).resolve().parents[2]
    exe = _find_devtrail(repo_root)
    if not exe:
        return 0

    # 한국어 Windows 콘솔(cp949)에서도 briefing 한글이 깨지지 않게 UTF-8을 강제한다.
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
    if not briefing:
        return 0

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
