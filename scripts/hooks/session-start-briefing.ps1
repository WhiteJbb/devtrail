# Claude Code SessionStart 훅 (Tier 1, docs/service-improvement-plan.md P3) — 참고용.
#
# work-agent get_project_briefing()을 additionalContext로 주입한다. 이 저장소의
# .claude/settings.json에는 등록하지 않았다 — 이 스크립트를 만드는 세션 자체가
# devtrail에서 도는 Claude Code 세션이라 등록 시 즉시 스스로에게 적용되기 때문이다.
# 실제 등록 전 별도 세션에서 반드시 검증할 것 (docs/vault-mcp-implementation-summary.md 참고).
#
# .claude/settings.json 등록 예:
#   "hooks": {
#     "SessionStart": [
#       { "hooks": [ { "type": "command", "command": "pwsh -File scripts/hooks/session-start-briefing.ps1" } ] }
#     ]
#   }

$ErrorActionPreference = "Stop"

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

$scriptPath = Join-Path $PSScriptRoot "print_briefing.py"
$briefingLines = & python $scriptPath $cwd 2>$null

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
