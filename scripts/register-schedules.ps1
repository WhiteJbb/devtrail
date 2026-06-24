# Windows Task Scheduler 등록
# 관리자 권한으로 실행 필요

$RepoRoot = Split-Path $PSScriptRoot -Parent
$PS = "powershell.exe"
$Flags = "-NonInteractive -ExecutionPolicy Bypass -File"

function Register($name, $trigger, $script) {
    $cmd = "$PS $Flags `"$script`""
    $result = schtasks /Create /TN $name /TR $cmd /RL HIGHEST /F $trigger 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $name" -ForegroundColor Green
    } else {
        Write-Host "  [!!] $name — $result" -ForegroundColor Red
    }
}

Write-Host "`nTask Scheduler 등록 중...`n" -ForegroundColor White

# 10분마다: work-agent 코드 업데이트 확인
Register "work-agent-update" `
    "/SC MINUTE /MO 10" `
    "$RepoRoot\scripts\update-work-agent.ps1"

# 10분마다: vault git 동기화
Register "work-agent-vault-sync" `
    "/SC MINUTE /MO 10" `
    "$RepoRoot\scripts\sync-vault.ps1"

# 매일 23:30: nightly 전체 파이프라인
Register "work-agent-nightly" `
    "/SC DAILY /ST 23:30" `
    "$RepoRoot\scripts\run-nightly-safe.ps1"

# 매주 금요일 23:00: weekly distill (7일치 종합 정제)
$wa = "$RepoRoot\.venv\Scripts\work-agent.exe"
$weeklyCmd = "$PS -NonInteractive -ExecutionPolicy Bypass -Command `"& '$wa' weekly-distill`""
$result = schtasks /Create /TN "work-agent-weekly" /TR $weeklyCmd /RL HIGHEST /F /SC WEEKLY /D FRI /ST 23:00 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [OK] work-agent-weekly" -ForegroundColor Green
} else {
    Write-Host "  [!!] work-agent-weekly -- $result" -ForegroundColor Red
}

# 시작 시: Telegram 봇 (크래시 시 자동 재시작)
Register "work-agent-bot" `
    "/SC ONSTART /DELAY 0000:30" `
    "$RepoRoot\scripts\run-bot-service.ps1"

Write-Host ""
Write-Host "등록된 작업 확인:" -ForegroundColor White
foreach ($tn in @("work-agent-bot", "work-agent-update", "work-agent-vault-sync", "work-agent-nightly", "work-agent-weekly")) {
    $q = schtasks /Query /TN $tn /FO LIST 2>$null
    $status  = ($q | Where-Object { $_ -match "^Status" }  | Select-Object -First 1) -replace "^Status\s*:\s*", ""
    $nextRun = ($q | Where-Object { $_ -match "^Next Run" } | Select-Object -First 1) -replace "^Next Run Time\s*:\s*", ""
    Write-Host "  $tn  [$status]  next: $nextRun"
}

Write-Host ""
Write-Host "삭제하려면:" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-update     /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-vault-sync /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-bot        /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-nightly    /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-weekly     /F" -ForegroundColor DarkGray
