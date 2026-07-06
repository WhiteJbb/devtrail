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

cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT"

log "=== bot service start ==="

while true; do
    while [ -f "$UPDATE_LOCK" ]; do
        log "Update in progress, waiting..."
        sleep 3
    done

    log "Starting bot..."
    "$WA" serve-bot 2>&1 | while IFS= read -r l; do log "  $l"; done
    code=$?
    log "Bot exited (code=$code). Restarting in 10s..."
    sleep 10
done
