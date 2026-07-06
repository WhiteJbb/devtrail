# Claude Code Stop/PreCompact 훅 (Tier 1, docs/service-improvement-plan.md P3) — 참고용.
#
# git 작업 디렉터리가 dirty한데 이번 MCP 세션에서 write_session_process가 호출되지
# 않았으면 세션 종료를 차단하고 리마인드한다. 파일 변경이 없는 세션은 조용히 통과시킨다
# (§3d Process 생략 기준과 동일). 이 저장소의 .claude/settings.json에는 등록하지 않았다
# — 이 스크립트를 만드는 세션 자체가 devtrail에서 도는 Claude Code 세션이라 등록 시
# 즉시 스스로에게 적용되기 때문이다. 실제 등록 전 별도 세션에서 반드시 검증할 것
# (docs/vault-mcp-implementation-summary.md 참고).
#
# 알려진 한계: 마커는 저장소당 파일 1개라 같은 repo에서 동시에 여러 MCP 세션이
# 돌면 서로의 상태를 덮어쓸 수 있다. 완전한 해결은 세션별 마커 파일이 필요하며
# 이번 범위에서는 다루지 않는다.
#
# .claude/settings.json 등록 예:
#   "hooks": {
#     "Stop": [ { "hooks": [ { "type": "command", "command": "pwsh -File scripts/hooks/stop-process-check.ps1" } ] } ],
#     "PreCompact": [ { "hooks": [ { "type": "command", "command": "pwsh -File scripts/hooks/stop-process-check.ps1" } ] } ]
#   }

$ErrorActionPreference = "Stop"

# 한국어 Windows 기본 콘솔 인코딩(cp949)으로 디코딩하면 차단 메시지의 한글이 깨진다.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

try {
    $stdinText = [Console]::In.ReadToEnd()
    $payload = $stdinText | ConvertFrom-Json -ErrorAction SilentlyContinue
} catch {
    $payload = $null
}

# Claude Code가 차단 결정을 해소할 수 없어 이미 강제로 계속 실행 중이면 다시
# 차단하지 않는다(공식 문서가 stop_hook_active 확인을 요구) — 그렇지 않으면
# 매 Stop마다 block을 반복해 8회 연속 차단 후에야 강제 해제되고 그때까지
# 불필요하게 계속 실행된다.
if ($payload -and $payload.stop_hook_active) {
    exit 0
}

if ($payload -and $payload.cwd) {
    $cwd = $payload.cwd
} else {
    $cwd = (Get-Location).Path
}

# git 부재/실패가 훅 전체를 죽이지 않도록 이 블록만 EAP를 낮추고 감싼다.
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$gitStatus = $null
try {
    Push-Location $cwd
    $gitStatus = & git status --porcelain
} catch {
    $gitStatus = $null
} finally {
    Pop-Location
    $ErrorActionPreference = $previousEap
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
        $updatedAt = [datetime]$marker.updated_at
        $isStale = ((Get-Date) - $updatedAt).TotalHours -ge 12
        if (-not $isStale) {
            $processWritten = [bool]$marker.process_written
        }
        # stale 마커(12시간 이상 지남)는 이전 세션의 잔존 파일로 간주해 무시한다 —
        # 그렇지 않으면 예전 세션의 process_written=true가 이번 MCP 미연결 세션을
        # 잘못 통과시킬 수 있다.
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
