# 로컬 개발 머신용 Task Scheduler 등록
# 관리자 권한으로 실행 필요

$RepoRoot = Split-Path $PSScriptRoot -Parent
$PS       = "powershell.exe"
$Flags    = "-NonInteractive -ExecutionPolicy Bypass -File"

function Register($name, $triggerStr, $script) {
    $cmd         = "$PS $Flags `"$script`""
    $triggerArgs = $triggerStr -split '\s+'
    $result = & schtasks /Create /TN $name /TR $cmd /RL HIGHEST /F @triggerArgs 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $name" -ForegroundColor Green
    } else {
        Write-Host "  [!!] $name - $($result -join ' ')" -ForegroundColor Red
    }
}

function Set-PowerPolicy($name) {
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

Write-Host "`n로컬 Task Scheduler 등록 중...`n" -ForegroundColor White

# 10분마다: vault git 동기화
Register "work-agent-vault-sync" "/SC MINUTE /MO 10" "$RepoRoot\scripts\sync-vault.ps1"

Set-PowerPolicy "work-agent-vault-sync"

Write-Host ""
Write-Host "삭제하려면:" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-vault-sync /F" -ForegroundColor DarkGray
