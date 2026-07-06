#!/bin/bash
# 아침/저녁 알림 실행 wrapper (macOS)
# 사용법: run-notify.sh morning|evening

set -uo pipefail

KIND="${1:-}"
if [ "$KIND" != "morning" ] && [ "$KIND" != "evening" ]; then
    echo "Usage: run-notify.sh morning|evening" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_FILE="$REPO_ROOT/logs/notify.log"

mkdir -p "$REPO_ROOT/logs"

log() {
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S')  $1"
    echo "$line"
    echo "$line" >> "$LOG_FILE"
}

VENV_WA="$REPO_ROOT/.venv/bin/devtrail"
if [ -x "$VENV_WA" ]; then
    WA="$VENV_WA"
else
    WA="$(command -v devtrail || true)"
fi
if [ -z "$WA" ]; then
    log "ERROR: devtrail을 찾을 수 없습니다: $VENV_WA"
    exit 1
fi

cd "$REPO_ROOT"

log "notify $KIND ..."
"$WA" notify "$KIND" 2>&1 | while IFS= read -r l; do log "  $l"; done
log "notify $KIND done"
