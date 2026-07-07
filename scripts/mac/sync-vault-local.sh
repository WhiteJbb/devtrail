#!/bin/bash
# Vault git sync - local machine variant (macOS)
# Tracks ALL changes (git add -A) instead of AI folders only
# Use sync-vault.sh on the server (AI folders only)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_FILE="$REPO_ROOT/logs/sync-vault-local.log"

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

VAULT_DIR="$(get_env_var OBSIDIAN_VAULT_PATH)"
if [ -z "$VAULT_DIR" ] || [ ! -d "$VAULT_DIR" ]; then
    log "ERROR: OBSIDIAN_VAULT_PATH not set or not found: '$VAULT_DIR'"
    exit 1
fi

cd "$VAULT_DIR"

if [ -f ".git/MERGE_HEAD" ] || [ -d ".git/rebase-merge" ]; then
    msg="[vault-local] Conflict detected. Manual fix needed: $VAULT_DIR"
    log "ERROR: $msg"
    send_telegram_alert "$msg"
    exit 1
fi

git fetch origin 2>&1 | while IFS= read -r l; do log "fetch: $l"; done

has_local=0
[ -n "$(git status --porcelain 2>&1)" ] && has_local=1

local_rev="$(git rev-parse HEAD)"
remote_rev="$(git rev-parse '@{u}' 2>&1)"
has_remote=0
[ "$local_rev" != "$remote_rev" ] && has_remote=1

if [ "$has_local" -eq 0 ] && [ "$has_remote" -eq 0 ]; then
    log "Nothing to sync."
    exit 0
fi

log "=== sync-vault-local start === (local=$has_local remote=$has_remote)"

if [ "$has_local" -eq 1 ]; then
    git add -A 2>&1 | while IFS= read -r l; do log "add: $l"; done
    commit_msg="auto: vault sync $(date '+%Y-%m-%d %H:%M')"
    git commit -m "$commit_msg" 2>&1 | while IFS= read -r l; do log "commit: $l"; done
    log "Committed local changes."
fi

if [ "$has_remote" -eq 1 ] || [ "$has_local" -eq 1 ]; then
    if ! git pull --no-rebase 2>&1 | while IFS= read -r l; do log "pull: $l"; done; then
        msg="[vault-local] Merge failed. Manual fix needed: $VAULT_DIR"
        log "ERROR: $msg"
        send_telegram_alert "$msg"
        exit 1
    fi
    if [ -f ".git/MERGE_HEAD" ] || [ -d ".git/rebase-merge" ]; then
        msg="[vault-local] Merge conflict detected. Manual fix needed: $VAULT_DIR"
        log "ERROR: $msg"
        send_telegram_alert "$msg"
        exit 1
    fi
fi

if [ "$has_local" -eq 1 ]; then
    if ! git push 2>&1 | while IFS= read -r l; do log "push: $l"; done; then
        msg="[vault-local] Push failed"
        log "ERROR: $msg"
        send_telegram_alert "$msg"
        exit 1
    fi
fi

log "sync-vault-local done"
