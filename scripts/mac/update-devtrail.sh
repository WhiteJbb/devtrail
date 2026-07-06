#!/bin/bash
# devtrail 코드 자동 업데이트 (macOS)
# 로컬 변경이 있으면 건너뜀. 새 커밋이 있으면 pull.
# pyproject.toml 변경 시에만 pip 재설치 (editable install은 소스 변경 자동 반영)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_FILE="$REPO_ROOT/logs/update-devtrail.log"
LOCK_FILE="$REPO_ROOT/.update.lock"

mkdir -p "$REPO_ROOT/logs"

log() {
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S')  $1"
    echo "$line"
    echo "$line" >> "$LOG_FILE"
}

log "=== update-devtrail start ==="

cd "$REPO_ROOT"

dirty="$(git status --porcelain 2>&1)"
if [ -n "$dirty" ]; then
    log "Local changes detected — skip auto update."
    echo "$dirty" | while IFS= read -r l; do log "  $l"; done
    exit 0
fi

git fetch origin 2>&1 | while IFS= read -r l; do log "fetch: $l"; done

local_rev="$(git rev-parse HEAD)"
remote_rev="$(git rev-parse '@{u}' 2>&1)"

if [ "$local_rev" = "$remote_rev" ]; then
    log "Already up to date."
    exit 0
fi

pyproject_changed=""
if git diff HEAD "$remote_rev" --name-only 2>&1 | grep -q 'pyproject\.toml'; then
    pyproject_changed=1
fi

log "New commits detected. Pulling..."
if ! git pull --ff-only 2>&1 | while IFS= read -r l; do log "pull: $l"; done; then
    log "ERROR: git pull failed"
    exit 1
fi

if [ -z "$pyproject_changed" ]; then
    log "pyproject.toml unchanged — editable install auto-reflects source changes. Done."
    exit 0
fi

log "pyproject.toml changed — reinstalling package..."

: > "$LOCK_FILE"
log "Update lock created."

cleanup() {
    rm -f "$LOCK_FILE"
    log "Update lock released."
}
trap cleanup EXIT

log "Stopping devtrail process tree..."
pkill -f "$REPO_ROOT/.venv/bin/devtrail" 2>/dev/null || true
sleep 3

for d in "$REPO_ROOT"/.venv/lib/python3.*/site-packages/~*; do
    [ -e "$d" ] || continue
    rm -rf "$d"
    log "Cleaned stale pip temp: $(basename "$d")"
done

VENV_PY="$REPO_ROOT/.venv/bin/python"
if [ -x "$VENV_PY" ]; then
    PY="$VENV_PY"
else
    PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ]; then
    log "ERROR: python을 찾을 수 없습니다"
    exit 1
fi

if ! "$PY" -m pip install -e "$REPO_ROOT" 2>&1 | while IFS= read -r l; do log "pip: $l"; done; then
    log "ERROR: pip install failed"
    exit 1
fi

log "update-devtrail done"
