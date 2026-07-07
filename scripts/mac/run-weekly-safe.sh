#!/bin/bash
# weekly-distill 안전 실행 wrapper (macOS)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_FILE="$REPO_ROOT/logs/weekly.log"
LOCK_FILE="$REPO_ROOT/.weekly.lock"

mkdir -p "$REPO_ROOT/logs"

log() {
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S')  $1"
    echo "$line"
    echo "$line" >> "$LOG_FILE"
}

get_env_var() {
    local key="$1" env_path="$REPO_ROOT/.env"
    [ -f "$env_path" ] || return
    grep -E "^\s*${key}\s*=" "$env_path" | head -1 | cut -d '=' -f2- \
        | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e "s/^[\"']//" -e "s/[\"']$//"
}

send_telegram_alert() {
    local text="$1" token chat_id
    token="$(get_env_var TELEGRAM_BOT_TOKEN)"
    chat_id="$(get_env_var TELEGRAM_CHAT_ID)"
    [ -z "$token" ] && return
    [ -z "$chat_id" ] && return
    curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
        --data-urlencode "chat_id=${chat_id}" \
        --data-urlencode "text=${text}" > /dev/null || log "Telegram alert failed"
}

VENV_WA="$REPO_ROOT/.venv/bin/devtrail"
if [ -x "$VENV_WA" ]; then
    WA="$VENV_WA"
else
    WA="$(command -v devtrail || true)"
fi

if [ -f "$LOCK_FILE" ]; then
    age_sec=$(( $(date +%s) - $(stat -f %m "$LOCK_FILE") ))
    if [ "$age_sec" -lt 14400 ]; then
        log "Lock exists ($((age_sec / 60))min ago). Exit."
        exit 0
    fi
    log "Stale lock (over 4h). Removing and continuing."
    rm -f "$LOCK_FILE"
fi

: > "$LOCK_FILE"
cleanup() { rm -f "$LOCK_FILE"; }
trap cleanup EXIT

log "=== run-weekly-safe start ==="

cd "$REPO_ROOT"

if [ -z "$WA" ]; then
    log "ERROR: devtrail을 찾을 수 없습니다"
    exit 1
fi

if "$WA" weekly-distill 2>&1 | while IFS= read -r l; do log "  $l"; done; then
    log "=== run-weekly-safe done ==="
else
    msg="[devtrail] weekly-distill failed"
    log "ERROR: $msg"
    send_telegram_alert "$msg"
    exit 1
fi
