#!/bin/bash
# macOS launchd 자동화 등록 (Windows register-schedules.ps1의 mac 대응)
# ~/Library/LaunchAgents에 devtrail-* plist 7개를 설치하고 로드한다.
#
# LaunchAgent는 사용자가 로그인해야 동작한다. 로그인 없이도 완전히 24시간
# 구동하려면 /Library/LaunchDaemons(root 권한, sudo)로 바꿔야 하며, 이 경우
# .env를 읽는 경로/권한을 별도로 확인해야 한다. 이 스크립트는 LaunchAgent
# 기준으로만 등록한다.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/launchd"
TARGET_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$TARGET_DIR"

install_plist() {
    local template="$1" label="$2"
    local dest="$TARGET_DIR/${label}.plist"

    launchctl unload "$dest" 2>/dev/null || true
    sed "s|__REPO_ROOT__|${REPO_ROOT}|g" "$template" > "$dest"

    if launchctl load -w "$dest" 2>&1; then
        echo "  [OK] $label"
    else
        echo "  [!!] $label - load 실패"
    fi
}

echo ""
echo "launchd 작업 등록 중..."
echo ""

install_plist "$TEMPLATE_DIR/com.devtrail.bot.plist.template"            "com.devtrail.bot"
install_plist "$TEMPLATE_DIR/com.devtrail.update.plist.template"         "com.devtrail.update"
install_plist "$TEMPLATE_DIR/com.devtrail.vault-sync.plist.template"     "com.devtrail.vault-sync"
install_plist "$TEMPLATE_DIR/com.devtrail.nightly.plist.template"        "com.devtrail.nightly"
install_plist "$TEMPLATE_DIR/com.devtrail.weekly.plist.template"         "com.devtrail.weekly"
install_plist "$TEMPLATE_DIR/com.devtrail.notify-morning.plist.template" "com.devtrail.notify-morning"
install_plist "$TEMPLATE_DIR/com.devtrail.notify-evening.plist.template" "com.devtrail.notify-evening"

echo ""
echo "등록 결과 확인:"
launchctl list | grep devtrail || echo "  (없음)"

echo ""
echo "삭제하려면:"
for label in com.devtrail.bot com.devtrail.update com.devtrail.vault-sync com.devtrail.nightly com.devtrail.weekly com.devtrail.notify-morning com.devtrail.notify-evening; do
    echo "  launchctl unload \"$TARGET_DIR/${label}.plist\" && rm \"$TARGET_DIR/${label}.plist\""
done
