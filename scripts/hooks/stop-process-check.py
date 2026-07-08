"""Claude Code Stop/PreCompact 훅 — write_session_process 미기록 세션 종료를 차단한다.

scripts/hooks/run-hook.sh가 OS에 맞는 python으로 실행하는 크로스플랫폼 구현.
(기존 scripts/windows/hooks/stop-process-check.ps1의 포트 — ps1은 참고용으로 유지)

"작업이 있었던 세션"의 판정은 두 가지를 함께 본다:
  1. git 작업 디렉터리가 dirty (커밋 안 된 변경이 남음)
  2. 세션 시작(마커 생성) 이후 새 커밋이 존재 (커밋/머지로 깔끔하게 끝낸 세션)
2번이 없으면 feat 브랜치 → 커밋 → PR 머지로 끝낸, 기록 가치가 가장 높은 세션일수록
tree가 clean해서 기록 없이 통과하는 역설이 생긴다. 둘 다 아니면(읽기만 한 세션)
조용히 통과시킨다.

process_written=true여도 마지막 기록(마커 갱신) 이후 새 커밋이 있으면 한 번 더
차단한다 — Process가 세션 중간 스냅샷으로 낡으면 다음 세션 briefing이 이미 끝난
Next Session 항목을 지시한다. 재호출은 같은 세션 기록을 갱신(upsert)한다.

알려진 한계: 마커는 저장소당 파일 1개라 같은 repo에서 동시에 여러 MCP 세션이
돌면 서로의 상태를 덮어쓸 수 있다.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _read_payload():
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else None
    except Exception:
        return None


def _emit_block(reason: str) -> None:
    output = {"decision": "block", "reason": reason}
    sys.stdout.buffer.write(json.dumps(output).encode("utf-8"))


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

    # Claude Code가 차단 결정을 해소할 수 없어 이미 강제로 계속 실행 중이면 다시
    # 차단하지 않는다(공식 문서가 stop_hook_active 확인을 요구).
    if payload.get("stop_hook_active"):
        return 0

    cwd = payload.get("cwd") or os.getcwd()

    # 마커를 먼저 읽는다 — process_written이면 아래 git 검사 없이 바로 통과하고,
    # 아니면 marker 생성 시각(= MCP 세션 시작)을 세션 중 커밋 검출의 기준점으로 쓴다.
    # stale 마커(12시간 이상)는 이전 세션의 잔존 파일로 간주해 무시한다.
    process_written = False
    session_started_at = None
    marker_path = Path(cwd) / ".claude" / ".vault-mcp" / "current_session.json"
    if marker_path.exists():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            updated_at = datetime.fromisoformat(str(marker["updated_at"]))
            now = datetime.now(updated_at.tzinfo) if updated_at.tzinfo else datetime.now()
            if now - updated_at < timedelta(hours=12):
                process_written = bool(marker.get("process_written"))
                session_started_at = updated_at
        except Exception:
            process_written = False

    # 마커 시각(session_started_at)은 MCP 세션 시작 시각이자, process가 기록됐다면
    # 마지막 기록 시각이다(write_session_process가 마커를 다시 쓴다). 따라서 이 시각
    # 이후의 커밋은 두 경우 모두 "아직 기록되지 않은 작업"을 뜻한다.
    git_status = _git(["status", "--porcelain"], cwd)
    session_commits = None
    if session_started_at:
        # 훅과 MCP 서버가 같은 머신에서 돌므로 로컬 시각 비교로 충분하다.
        since = session_started_at.strftime("%Y-%m-%dT%H:%M:%S")
        session_commits = _git(["log", "--since", since, "-1", "--format=%H"], cwd)

    if process_written:
        if session_commits:
            _emit_block(
                "write_session_process 기록 이후에 새 커밋이 생겼습니다. "
                "Process가 세션 중간 스냅샷으로 낡았으니, 이후 작업을 반영해 "
                "write_session_process를 다시 호출하세요 (같은 세션 기록이 갱신됩니다)."
            )
        return 0

    if not git_status and not session_commits:
        # 변경도 없고 이번 세션의 커밋도 없다 — Process를 생략할 수 있다
        return 0

    if session_commits and not git_status:
        reason = (
            "이번 세션에서 커밋이 만들어졌는데 write_session_process가 호출되지 "
            "않았습니다. tree가 clean해도 커밋으로 끝난 세션은 기록 가치가 가장 "
            "높습니다 — 세션을 마치기 전에 write_session_process로 Process를 남기세요."
        )
    else:
        reason = (
            "git 작업 디렉터리에 변경이 있는데 이번 세션의 write_session_process가 "
            "호출되지 않았습니다. 세션을 마치기 전에 write_session_process로 "
            "Process를 남기세요."
        )
    _emit_block(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
