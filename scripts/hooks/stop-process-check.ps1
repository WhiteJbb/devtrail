# Claude Code Stop/PreCompact 훅 (Tier 1, docs/service-improvement-plan.md P3) — 참고용.
#
# git 작업 디렉터리가 dirty한데 이번 MCP 세션에서 write_session_process가 호출되지
# 않았으면 세션 종료를 차단하고 리마인드한다. 파일 변경이 없는 세션은 조용히 통과시킨다
# (§3d Process 생략 기준과 동일). 이 저장소의 .claude/settings.json에는 등록하지 않았다
# — 이 스크립트를 만드는 세션 자체가 devtrail에서 도는 Claude Code 세션이라 등록 시
# 즉시 스스로에게 적용되기 때문이다. 실제 등록 전 별도 세션에서 반드시 검증할 것
# (docs/vault-mcp-implementation-summary.md 참고).
#
# .claude/settings.json 등록 예:
#   "hooks": {
#     "Stop": [ { "hooks": [ { "type": "command", "command": "pwsh -File scripts/hooks/stop-process-check.ps1" } ] } ],
#     "PreCompact": [ { "hooks": [ { "type": "command", "command": "pwsh -File scripts/hooks/stop-process-check.ps1" } ] } ]
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

Push-Location $cwd
try {
    $gitStatus = git status --porcelain 2>$null
} catch {
    $gitStatus = $null
} finally {
    Pop-Location
}

if (-not $gitStatus) {
    # 파일 변경이 없는 세션은 Process를 생략할 수 있다 (§3d) — 조용히 통과
    exit 0
}

$processWritten = $false
$markerPath = Join-Path $cwd ".claude/.vault-mcp/current_session.json"
if (Test-Path $markerPath) {
    try {
        $marker = Get-Content $markerPath -Raw | ConvertFrom-Json
        $processWritten = [bool]$marker.process_written
    } catch {
        $processWritten = $false
    }
}

if ($processWritten) {
    exit 0
}

$output = @{
    decision = "block"
    reason   = "git 작업 디렉터리에 변경이 있는데 이번 세션의 write_session_process가 호출되지 않았습니다. 세션을 마치기 전에 write_session_process로 Process를 남기세요."
} | ConvertTo-Json -Compress

Write-Output $output
exit 0
