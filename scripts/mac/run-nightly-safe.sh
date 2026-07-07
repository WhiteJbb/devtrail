#!/bin/bash
# nightly 안전 실행 wrapper (macOS)
# update-devtrail → sync-vault(pull) → nightly-distill → push-digest → sync-vault(push)
# 충돌/오류 발생 시 중단 + Telegram 알림

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_FILE="$REPO_ROOT/logs/nightly.log"
LOCK_FILE="$REPO_ROOT/.nightly.lock"
WEEKLY_LOCK="$REPO_ROOT/.weekly.lock"

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

invoke_step() {
    local name="$1"; shift
    log "--- $name ---"
    if "$@" 2>&1 | while IFS= read -r l; do log "  $l"; done; then
        log "$name OK"
        return 0
    else
        local msg="[devtrail] nightly 실패 — $name"
        log "ERROR: $msg"
        send_telegram_alert "$msg"
        return 1
    fi
}

# ── weekly 실행 중이면 대기 ── (stat -f는 macOS BSD stat 기준)
if [ -f "$WEEKLY_LOCK" ]; then
    age_sec=$(( $(date +%s) - $(stat -f %m "$WEEKLY_LOCK") ))
    if [ "$age_sec" -lt 14400 ]; then
        log "Weekly distill 실행 중 ($((age_sec / 60))min). 완료까지 대기..."
        waited=0
        while [ -f "$WEEKLY_LOCK" ] && [ "$waited" -lt 60 ]; do
            sleep 60
            waited=$((waited + 1))
        done
        if [ -f "$WEEKLY_LOCK" ]; then
            log "WARNING: Weekly lock 60분 초과. 강제 진행."
        else
            log "Weekly 완료 확인. Nightly 시작."
        fi
    fi
fi

# ── 중복 실행 방지 ──
if [ -f "$LOCK_FILE" ]; then
    age_sec=$(( $(date +%s) - $(stat -f %m "$LOCK_FILE") ))
    if [ "$age_sec" -lt 14400 ]; then
        log "Lock exists (created $((age_sec / 60))min ago). Exit."
        exit 0
    fi
    log "Stale lock (over 4h). Removing and continuing."
    rm -f "$LOCK_FILE"
fi

: > "$LOCK_FILE"
cleanup() { rm -f "$LOCK_FILE"; }
trap cleanup EXIT

VENV_WA="$REPO_ROOT/.venv/bin/devtrail"
if [ -x "$VENV_WA" ]; then
    WA="$VENV_WA"
else
    WA="$(command -v devtrail || true)"
fi
if [ -z "$WA" ]; then
    log "devtrail을 찾을 수 없습니다 (.venv 없고 PATH에도 없음)."
    exit 1
fi

log "==============================="
log "=== run-nightly-safe start ==="
log "==============================="

invoke_step "update-devtrail" "$REPO_ROOT/scripts/mac/update-devtrail.sh" || exit 1
invoke_step "sync-vault (pull)" "$REPO_ROOT/scripts/mac/sync-vault.sh" --internal || exit 1

cd "$REPO_ROOT"
invoke_step "nightly-distill" "$WA" nightly-distill || exit 1
invoke_step "push-digest" "$WA" push-digest --daily || exit 1
invoke_step "sync-vault (push)" "$REPO_ROOT/scripts/mac/sync-vault.sh" --internal --commit-msg "auto: nightly distill $(date '+%Y-%m-%d')" || exit 1

log "=== run-nightly-safe done ==="
