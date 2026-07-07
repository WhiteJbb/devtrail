# Claude Code Stop/PreCompact 훅 (Tier 1, docs/service-improvement-plan.md P3) — 참고용.
#
# 이번 MCP 세션에서 write_session_process가 호출되지 않은 채로 세션을 끝내려 하면
# 차단하고 리마인드한다. "작업이 있었던 세션"의 판정은 두 가지를 함께 본다:
#   1. git 작업 디렉터리가 dirty (커밋 안 된 변경이 남음)
#   2. 세션 시작(마커 생성) 이후 새 커밋이 존재 (커밋/머지로 깔끔하게 끝낸 세션)
# 2번이 없으면 feat 브랜치 → 커밋 → PR 머지로 끝낸, 기록 가치가 가장 높은 세션일수록
# tree가 clean해서 기록 없이 통과하는 역설이 생긴다. 둘 다 아니면(읽기만 한 세션)
# §3d Process 생략 기준대로 조용히 통과시킨다.
#
# 알려진 한계: 마커는 저장소당 파일 1개라 같은 repo에서 동시에 여러 MCP 세션이
# 돌면 서로의 상태를 덮어쓸 수 있다. 완전한 해결은 세션별 마커 파일이 필요하며
# 이번 범위에서는 다루지 않는다.
#
# .claude/settings.json 등록 예:
#   "hooks": {
#     "Stop": [ { "hooks": [ { "type": "command", "command": "pwsh -File scripts/windows/hooks/stop-process-check.ps1" } ] } ],
#     "PreCompact": [ { "hooks": [ { "type": "command", "command": "pwsh -File scripts/windows/hooks/stop-process-check.ps1" } ] } ]
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

# 마커를 먼저 읽는다 — process_written이면 아래 git 검사 없이 바로 통과하고,
# 아니면 marker 생성 시각(= MCP 세션 시작)을 세션 중 커밋 검출의 기준점으로 쓴다.
$processWritten = $false
$sessionStartedAt = $null
$markerPath = Join-Path $cwd ".claude/.vault-mcp/current_session.json"
if (Test-Path $markerPath) {
    try {
        $marker = Get-Content $markerPath -Raw | ConvertFrom-Json
        $updatedAt = [datetime]$marker.updated_at
        $isStale = ((Get-Date) - $updatedAt).TotalHours -ge 12
        if (-not $isStale) {
            $processWritten = [bool]$marker.process_written
            $sessionStartedAt = $updatedAt
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

# git 부재/실패가 훅 전체를 죽이지 않도록 이 블록만 EAP를 낮추고 감싼다.
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$gitStatus = $null
$sessionCommits = $null
try {
    Push-Location $cwd
    $gitStatus = & git status --porcelain
    if ($sessionStartedAt) {
        # 마커 생성 이후의 커밋 = 이번 세션에서 만든 커밋. 훅과 MCP 서버가 같은
        # 머신에서 돌므로 로컬 시각 비교로 충분하다.
        $sinceArg = $sessionStartedAt.ToString("yyyy-MM-ddTHH:mm:ss")
        $sessionCommits = & git log --since $sinceArg -1 --format=%H
    }
} catch {
    $gitStatus = $null
    $sessionCommits = $null
} finally {
    Pop-Location
    $ErrorActionPreference = $previousEap
}

if (-not $gitStatus -and -not $sessionCommits) {
    # 변경도 없고 이번 세션의 커밋도 없다 — Process를 생략할 수 있다 (§3d)
    exit 0
}

if ($sessionCommits -and -not $gitStatus) {
    $reason = "이번 세션에서 커밋이 만들어졌는데 write_session_process가 호출되지 않았습니다. tree가 clean해도 커밋으로 끝난 세션은 기록 가치가 가장 높습니다 — 세션을 마치기 전에 write_session_process로 Process를 남기세요."
} else {
    $reason = "git 작업 디렉터리에 변경이 있는데 이번 세션의 write_session_process가 호출되지 않았습니다. 세션을 마치기 전에 write_session_process로 Process를 남기세요."
}

$output = @{
    decision = "block"
    reason   = $reason
} | ConvertTo-Json -Compress

Write-Output $output
exit 0
