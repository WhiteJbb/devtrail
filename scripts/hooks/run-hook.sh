#!/bin/sh
# Claude Code 훅 디스패처 — OS에 맞는 python으로 scripts/hooks/<이름>.py를 실행한다.
# 사용: sh scripts/hooks/run-hook.sh <session-start-briefing|stop-process-check>
#
# Windows에서는 Git for Windows의 sh.exe(PATH의 usr/bin)로, macOS에서는 /bin/sh로
# 동일하게 동작한다 — 훅 로직을 OS별로 복제하지 않기 위한 단일 진입점이다.
# python 부재는 조용히 통과시킨다: 훅 실패가 세션 진행을 막아서는 안 된다.

set -u

HOOK_NAME="${1:?usage: run-hook.sh <hook-name>}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PY="$REPO_ROOT/.venv/bin/python"
elif [ -f "$REPO_ROOT/.venv/Scripts/python.exe" ]; then
    PY="$REPO_ROOT/.venv/Scripts/python.exe"
else
    PY="$(command -v python3 || command -v python || true)"
fi
[ -n "$PY" ] || exit 0

exec "$PY" "$SCRIPT_DIR/${HOOK_NAME}.py"
