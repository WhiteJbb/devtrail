# Windows Task Scheduler 등록
# 관리자 권한으로 실행 필요

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

# wscript(VBS) 래퍼 경유 실행 — 콘솔 창 깜빡임 없이 완전 백그라운드 실행
$Hidden = "wscript.exe //B //Nologo `"$PSScriptRoot\run-hidden.vbs`""

function Register($name, $triggerStr, $script, $extraArgs = @()) {
    $cmd         = "$Hidden `"$script`""
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
Register "devtrail-bot" "/SC ONSTART" "$RepoRoot\scripts\windows\run-bot-service.ps1" @("/RU", "SYSTEM")

# 10분마다: devtrail 코드 업데이트
Register "devtrail-update" "/SC MINUTE /MO 10" "$RepoRoot\scripts\windows\update-devtrail.ps1"

# 10분마다: vault git 동기화
Register "devtrail-vault-sync" "/SC MINUTE /MO 10" "$RepoRoot\scripts\windows\sync-vault.ps1"

# 매일 23:30: nightly 전체 파이프라인
Register "devtrail-nightly" "/SC DAILY /ST 23:30" "$RepoRoot\scripts\windows\run-nightly-safe.ps1"

# 매주 일요일 18:00: weekly 회고 (한 주 daily digest 7개 종합)
Register "devtrail-weekly" "/SC WEEKLY /D SUN /ST 18:00" "$RepoRoot\scripts\windows\run-weekly-safe.ps1"

# 매일 08:00: 아침 할 일 알림
$notifyScript = "$RepoRoot\scripts\windows\run-notify.ps1"
$result = & schtasks /Create /TN "devtrail-notify-morning" /TR "$Hidden `"$notifyScript`" -Kind morning" /SC DAILY /ST 08:00 /RL HIGHEST /F 2>&1
if ($LASTEXITCODE -eq 0) { Write-Host "  [OK] devtrail-notify-morning" -ForegroundColor Green }
else { Write-Host "  [!!] devtrail-notify-morning - $($result -join ' ')" -ForegroundColor Red }

# 매일 21:30: 저녁 마무리 알림
$result = & schtasks /Create /TN "devtrail-notify-evening" /TR "$Hidden `"$notifyScript`" -Kind evening" /SC DAILY /ST 21:30 /RL HIGHEST /F 2>&1
if ($LASTEXITCODE -eq 0) { Write-Host "  [OK] devtrail-notify-evening" -ForegroundColor Green }
else { Write-Host "  [!!] devtrail-notify-evening - $($result -join ' ')" -ForegroundColor Red }

Write-Host ""
Write-Host "전원 설정 해제 중 (배터리/절전 제한 제거)..." -ForegroundColor White
foreach ($tn in @("devtrail-bot", "devtrail-update", "devtrail-vault-sync", "devtrail-nightly", "devtrail-weekly", "devtrail-notify-morning", "devtrail-notify-evening")) {
    Set-PowerPolicy $tn
}

Write-Host ""
Write-Host "등록 결과 확인:" -ForegroundColor White
foreach ($tn in @("devtrail-bot", "devtrail-update", "devtrail-vault-sync", "devtrail-nightly", "devtrail-weekly", "devtrail-notify-morning", "devtrail-notify-evening")) {
    schtasks /Query /TN $tn 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $tn" -ForegroundColor Green
    } else {
        Write-Host "  [!!] $tn - 등록되지 않음" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "삭제하려면:" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN devtrail-bot             /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN devtrail-update          /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN devtrail-vault-sync      /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN devtrail-nightly         /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN devtrail-weekly          /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN devtrail-notify-morning  /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN devtrail-notify-evening  /F" -ForegroundColor DarkGray
