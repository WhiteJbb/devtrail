# Claude Code SessionStart 훅 (Tier 1, docs/service-improvement-plan.md P3) — 참고용.
#
# devtrail get_project_briefing()을 additionalContext로 주입한다. 이 저장소의
# .claude/settings.json에는 등록하지 않았다 — 이 스크립트를 만드는 세션 자체가
# devtrail에서 도는 Claude Code 세션이라 등록 시 즉시 스스로에게 적용되기 때문이다.
# 실제 등록 전 별도 세션에서 반드시 검증할 것 (docs/vault-mcp-implementation-summary.md 참고).
#
# devtrail이 PATH에서 바로 실행 가능해야 한다(예: 이 훅을 쓸 venv에서
# `pip install -e .` 등으로 설치). 실행 실패는 이 스크립트를 죽이지 않고 조용히
# 건너뛴다 — SessionStart 훅은 세션 진행을 막아서는 안 된다.
#
# .claude/settings.json 등록 예:
#   "hooks": {
#     "SessionStart": [
#       { "hooks": [ { "type": "command", "command": "pwsh -File scripts/hooks/session-start-briefing.ps1" } ] }
#     ]
#   }

$ErrorActionPreference = "Stop"

# 한국어 Windows 기본 콘솔 인코딩(cp949)으로 디코딩하면 briefing의 한글이 깨진다.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

try {
    $stdinText = [Console]::In.ReadToEnd()
    $payload = $stdinText | ConvertFrom-Json -ErrorAction SilentlyContinue
    if ($payload -and $payload.cwd) {
        $cwd = $payload.cwd
    } else {
        $cwd = (Get-Location).Path
    }
} catch {
    $cwd = (Get-Location).Path
}

# 세션마다 clean start — 이전 세션이 남긴 마커가 이번 세션의 것으로 오인되지 않게
# 지운다. MCP 서버(devtrail mcp-serve)가 시작되면 main()이 새 마커를 쓴다.
$markerPath = Join-Path $cwd ".claude/.vault-mcp/current_session.json"
if (Test-Path $markerPath) {
    try { Remove-Item -Path $markerPath -Force -ErrorAction Stop } catch {}
}

# devtrail 부재/실패가 훅 전체를 죽이지 않도록 이 블록만 EAP를 낮추고 감싼다.
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$briefingLines = $null
try {
    $briefingLines = & devtrail project-briefing $cwd
} catch {
    $briefingLines = $null
}
$ErrorActionPreference = $previousEap

if (-not $briefingLines) {
    exit 0
}

$context = ($briefingLines -join "`n")

$output = @{
    hookSpecificOutput = @{
        hookEventName     = "SessionStart"
        additionalContext = $context
    }
} | ConvertTo-Json -Depth 5 -Compress

Write-Output $output
exit 0
