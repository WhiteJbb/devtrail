# Local machine Task Scheduler registration (vault sync only)
# Run as Administrator

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

function Register($name, $intervalMinutes, $script) {
    try {
        $action = New-ScheduledTaskAction `
            -Execute "powershell.exe" `
            -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""

        $trigger = New-ScheduledTaskTrigger `
            -RepetitionInterval (New-TimeSpan -Minutes $intervalMinutes) `
            -Once -At (Get-Date)

        # Hidden: 태스크 스케줄러가 창을 완전히 숨김 (WindowStyle Hidden만으론 부족)
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
