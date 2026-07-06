# Local machine Task Scheduler registration (vault sync only)
# Run as Administrator

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

function Register($name, $intervalMinutes, $script) {
    try {
        # wscript(VBS) 래퍼 경유 실행 — powershell.exe -WindowStyle Hidden은
        # 콘솔 창이 생성된 뒤 숨겨서 깜빡임이 남지만, WshShell.Run(cmd, 0)은
        # 창을 아예 만들지 않는다.
        $action = New-ScheduledTaskAction `
            -Execute "wscript.exe" `
            -Argument "//B //Nologo `"$PSScriptRoot\run-hidden.vbs`" `"$script`""

        $trigger = New-ScheduledTaskTrigger `
            -RepetitionInterval (New-TimeSpan -Minutes $intervalMinutes) `
            -Once -At (Get-Date)

        # -Hidden은 창이 아니라 작업 스케줄러 목록에서 태스크를 숨기는 옵션
        $settings = New-ScheduledTaskSettingsSet `
            -Hidden `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
        $settings.DisallowStartIfOnBatteries = $false
        $settings.StopIfGoingOnBatteries     = $false

        $principal = New-ScheduledTaskPrincipal `
            -UserId $env:USERNAME `
            -LogonType Interactive `
            -RunLevel Highest

        Register-ScheduledTask `
            -TaskName $name `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            -Force | Out-Null

        Write-Host "  [OK] $name" -ForegroundColor Green
    } catch {
        Write-Host "  [!!] $name - $_" -ForegroundColor Red
    }
}

Write-Host "`nRegistering local Task Scheduler tasks...`n" -ForegroundColor White

# Every 10 min: vault git sync (local variant - tracks all files)
Register "devtrail-vault-sync" 10 "$RepoRoot\scripts\windows\sync-vault-local.ps1"

Write-Host ""
Write-Host "To remove:" -ForegroundColor DarkGray
Write-Host "  Unregister-ScheduledTask -TaskName devtrail-vault-sync -Confirm:`$false" -ForegroundColor DarkGray
