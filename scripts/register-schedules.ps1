# Windows Task Scheduler 등록
# 관리자 권한으로 실행 필요

$RepoRoot = Split-Path $PSScriptRoot -Parent
$PS    = "powershell.exe"
$Flags = "-NonInteractive -ExecutionPolicy Bypass -File"


function Register($name, $triggerStr, $script, $extraArgs = @()) {
    $cmd         = "$PS $Flags `"$script`""
    $triggerArgs = $triggerStr -split '\s+'
    $result = & schtasks /Create /TN $name /TR $cmd /RL HIGHEST /F @triggerArgs @extraArgs 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $name" -ForegroundColor Green
    } else {
        Write-Host "  [!!] $name - $($result -join ' ')" -ForegroundColor Red
    }
}

function Set-PowerPolicy($name) {
    # 배터리 제한 해제 — 절전 복귀 시에도 태스크가 정상 실행되도록
    try {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
        $task.Settings.DisallowStartIfOnBatteries = $false
        $task.Settings.StopIfGoingOnBatteries     = $false
        Set-ScheduledTask -InputObject $task | Out-Null
        Write-Host "  [OK] $name 전원 설정 해제" -ForegroundColor Cyan
    } catch {
        Write-Host "  [!!] $name 전원 설정 실패: $_" -ForegroundColor Yellow
    }
}

Write-Host "`nTask Scheduler 등록 중...`n" -ForegroundColor White

# 시작 시: Telegram 봇 (SYSTEM으로 실행 — 로그인 없이도 동작)
Register "work-agent-bot" "/SC ONSTART" "$RepoRoot\scripts\run-bot-service.ps1" @("/RU", "SYSTEM")

# 10분마다: work-agent 코드 업데이트
Register "work-agent-update" "/SC MINUTE /MO 10" "$RepoRoot\scripts\update-work-agent.ps1"

# 10분마다: vault git 동기화
Register "work-agent-vault-sync" "/SC MINUTE /MO 10" "$RepoRoot\scripts\sync-vault.ps1"

# 매일 23:30: nightly 전체 파이프라인
Register "work-agent-nightly" "/SC DAILY /ST 23:30" "$RepoRoot\scripts\run-nightly-safe.ps1"

# 매주 금요일 23:00: weekly distill
Register "work-agent-weekly" "/SC WEEKLY /D FRI /ST 23:00" "$RepoRoot\scripts\run-weekly-safe.ps1"

# 매일 08:00: 아침 할 일 알림
$notifyScript = "$RepoRoot\scripts\run-notify.ps1"
$result = & schtasks /Create /TN "work-agent-notify-morning" /TR "$PS $Flags `"$notifyScript`" -Kind morning" /SC DAILY /ST 08:00 /RL HIGHEST /F 2>&1
if ($LASTEXITCODE -eq 0) { Write-Host "  [OK] work-agent-notify-morning" -ForegroundColor Green }
else { Write-Host "  [!!] work-agent-notify-morning - $($result -join ' ')" -ForegroundColor Red }

# 매일 21:30: 저녁 마무리 알림
$result = & schtasks /Create /TN "work-agent-notify-evening" /TR "$PS $Flags `"$notifyScript`" -Kind evening" /SC DAILY /ST 21:30 /RL HIGHEST /F 2>&1
if ($LASTEXITCODE -eq 0) { Write-Host "  [OK] work-agent-notify-evening" -ForegroundColor Green }
else { Write-Host "  [!!] work-agent-notify-evening - $($result -join ' ')" -ForegroundColor Red }

Write-Host ""
Write-Host "전원 설정 해제 중 (배터리/절전 제한 제거)..." -ForegroundColor White
foreach ($tn in @("work-agent-bot", "work-agent-update", "work-agent-vault-sync", "work-agent-nightly", "work-agent-weekly", "work-agent-notify-morning", "work-agent-notify-evening")) {
    Set-PowerPolicy $tn
}

Write-Host ""
Write-Host "등록 결과 확인:" -ForegroundColor White
foreach ($tn in @("work-agent-bot", "work-agent-update", "work-agent-vault-sync", "work-agent-nightly", "work-agent-weekly", "work-agent-notify-morning", "work-agent-notify-evening")) {
    schtasks /Query /TN $tn 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $tn" -ForegroundColor Green
    } else {
        Write-Host "  [!!] $tn - 등록되지 않음" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "삭제하려면:" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-bot             /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-update          /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-vault-sync      /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-nightly         /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-weekly          /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-notify-morning  /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-notify-evening  /F" -ForegroundColor DarkGray
