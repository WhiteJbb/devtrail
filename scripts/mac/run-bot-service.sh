#!/bin/bash
# Telegram 봇 상시 실행 wrapper (macOS)
# 봇이 종료되면 10초 후 자동 재시작

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_FILE="$REPO_ROOT/logs/bot.log"
UPDATE_LOCK="$REPO_ROOT/.update.lock"

mkdir -p "$REPO_ROOT/logs"

log() {
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S')  $1"
    echo "$line"
    echo "$line" >> "$LOG_FILE"
}

WA="$REPO_ROOT/.venv/bin/devtrail"
if [ ! -x "$WA" ]; then
    log "ERROR: devtrail not found: $WA"
    exit 1
fi

# caffeinate -i: 봇이 살아있는 동안 시스템 idle sleep 진입을 막는다.
# pmset 설정(sleep 0)이 macOS 업데이트 등으로 리셋돼도 봇이 안전망이 된다.
# (뚜껑 닫힘에 의한 sleep은 못 막는다 — 클램셸 모드 필요)
CAFFEINATE=""
if command -v caffeinate >/dev/null 2>&1; then
    CAFFEINATE="caffeinate -i"
else
    log "WARN: caffeinate not found — idle sleep 방지 없이 실행"
fi

cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT"

log "=== bot service start ==="

while true; do
    while [ -f "$UPDATE_LOCK" ]; do
        log "Update in progress, waiting..."
        sleep 3
    done

    log "Starting bot..."
    $CAFFEINATE "$WA" serve-bot 2>&1 | while IFS= read -r l; do log "  $l"; done
    code=$?
    log "Bot exited (code=$code). Restarting in 10s..."
    sleep 10
done
