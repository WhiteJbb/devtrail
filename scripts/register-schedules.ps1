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

Write-Host ""
Write-Host "등록된 작업 확인:" -ForegroundColor White
schtasks /Query /TN "work-agent-update"    /FO LIST 2>$null | Select-String "Status|Next Run"
schtasks /Query /TN "work-agent-vault-sync" /FO LIST 2>$null | Select-String "Status|Next Run"
schtasks /Query /TN "work-agent-nightly"   /FO LIST 2>$null | Select-String "Status|Next Run"

Write-Host ""
Write-Host "삭제하려면:" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-update     /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-vault-sync /F" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-nightly    /F" -ForegroundColor DarkGray
