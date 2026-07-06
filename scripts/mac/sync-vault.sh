#!/bin/bash
# Vault git 동기화 (macOS, 서버 변형)
# AI 폴더 변경만 커밋 → pull(merge) → push
# 충돌 감지 시 중단 + Telegram 알림
#
# 사용법: sync-vault.sh [--internal] [--commit-msg "메시지"]
#   --internal    nightly에서 호출 시 lock 체크 건너뜀

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_FILE="$REPO_ROOT/logs/sync-vault.log"
LOCK_FILE="$REPO_ROOT/.nightly.lock"

COMMIT_MSG=""
INTERNAL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --internal) INTERNAL=1; shift ;;
        --commit-msg) COMMIT_MSG="${2:-}"; shift 2 ;;
        *) shift ;;
    esac
done

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

if [ "$INTERNAL" -ne 1 ] && [ -f "$LOCK_FILE" ]; then
    log "Nightly lock active — skip vault sync."
    exit 0
fi

VAULT_DIR="$(get_env_var OBSIDIAN_VAULT_PATH)"
if [ -z "$VAULT_DIR" ] || [ ! -d "$VAULT_DIR" ]; then
    log "ERROR: OBSIDIAN_VAULT_PATH not set or not found: '$VAULT_DIR'"
    exit 1
fi

cd "$VAULT_DIR"

if [ -f ".git/MERGE_HEAD" ] || [ -d ".git/rebase-merge" ]; then
    msg="[devtrail] Vault 충돌 상태 감지. 수동 해결 필요: $VAULT_DIR"
    log "ERROR: $msg"
    send_telegram_alert "$msg"
    exit 1
fi

git fetch origin 2>&1 | while IFS= read -r l; do log "fetch: $l"; done

AI_FOLDERS=("00_Inbox" "10_Worklog" "20_Knowledge" "30_Projects" "50_Outputs" "60_Candidates" "70_Tasks")
has_local=0
for folder in "${AI_FOLDERS[@]}"; do
    if [ -d "$folder" ] && [ -n "$(git status --porcelain "$folder" 2>&1)" ]; then
        has_local=1
        break
    fi
done
if [ "$has_local" -eq 0 ] && [ -f "log.md" ] && [ -n "$(git status --porcelain log.md 2>&1)" ]; then
    has_local=1
fi

local_rev="$(git rev-parse HEAD)"
remote_rev="$(git rev-parse '@{u}' 2>&1)"
has_remote=0
[ "$local_rev" != "$remote_rev" ] && has_remote=1

if [ "$has_local" -eq 0 ] && [ "$has_remote" -eq 0 ]; then
    log "Nothing to sync."
    exit 0
fi

log "=== sync-vault start === (local=$has_local remote=$has_remote)"

if [ "$has_local" -eq 1 ]; then
    for folder in "${AI_FOLDERS[@]}"; do
        [ -d "$folder" ] && git add "$folder" 2>&1 | while IFS= read -r l; do log "add: $l"; done
    done
    [ -f "log.md" ] && git add "log.md" 2>&1 | while IFS= read -r l; do log "add: $l"; done

    [ -z "$COMMIT_MSG" ] && COMMIT_MSG="auto: vault sync $(date '+%Y-%m-%d %H:%M')"
    git commit -m "$COMMIT_MSG" 2>&1 | while IFS= read -r l; do log "commit: $l"; done
    log "Committed local changes."
fi

if [ "$has_remote" -eq 1 ] || [ "$has_local" -eq 1 ]; then
    if ! git pull --no-rebase 2>&1 | while IFS= read -r l; do log "pull: $l"; done; then
        msg="[devtrail] Vault merge 실패. 수동 해결 필요: $VAULT_DIR"
        log "ERROR: $msg"
        send_telegram_alert "$msg"
        exit 1
    fi
    if [ -f ".git/MERGE_HEAD" ] || [ -d ".git/rebase-merge" ]; then
        msg="[devtrail] Vault merge 충돌 감지. 수동 해결 필요: $VAULT_DIR"
        log "ERROR: $msg"
        send_telegram_alert "$msg"
        exit 1
    fi
fi

if [ "$has_local" -eq 1 ]; then
    if ! git push 2>&1 | while IFS= read -r l; do log "push: $l"; done; then
        msg="[devtrail] Vault push 실패"
        log "ERROR: $msg"
        send_telegram_alert "$msg"
        exit 1
    fi

    changed="$(git diff --name-only HEAD~1 HEAD 2>&1 | grep -v '^$' || true)"
    count="$(printf '%s\n' "$changed" | grep -c . || true)"
    preview="$(printf '%s\n' "$changed" | head -5)"
    more=""
    if [ "$count" -gt 5 ]; then
        more="
  ... 외 $((count - 5))개"
    fi
    send_telegram_alert "📥 Vault 업데이트 (${count}개 파일)
  ${preview}${more}"
fi

log "sync-vault done"
