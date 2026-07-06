#!/bin/bash
# macOS launchd 등록 (vault 동기화만, Windows register-local.ps1의 mac 대응)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEMPLATE="$SCRIPT_DIR/launchd/com.devtrail.vault-sync-local.plist.template"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET="$TARGET_DIR/com.devtrail.vault-sync-local.plist"

mkdir -p "$TARGET_DIR"

echo ""
echo "launchd 작업 등록 중..."
echo ""

launchctl unload "$TARGET" 2>/dev/null || true
sed "s|__REPO_ROOT__|${REPO_ROOT}|g" "$TEMPLATE" > "$TARGET"

if launchctl load -w "$TARGET" 2>&1; then
    echo "  [OK] com.devtrail.vault-sync-local"
else
    echo "  [!!] com.devtrail.vault-sync-local - load 실패"
fi

echo ""
echo "제거하려면:"
echo "  launchctl unload \"$TARGET\" && rm \"$TARGET\""
