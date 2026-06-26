# Local machine Task Scheduler registration (vault sync only)
# Run as Administrator

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
        Write-Host "  [OK] $name power policy cleared" -ForegroundColor Cyan
    } catch {
        Write-Host "  [!!] $name power policy failed: $_" -ForegroundColor Yellow
    }
}

Write-Host "`nRegistering local Task Scheduler tasks...`n" -ForegroundColor White

# Every 10 min: vault git sync (local variant - tracks all files)
Register "work-agent-vault-sync" "/SC MINUTE /MO 10" "$RepoRoot\scripts\sync-vault-local.ps1"

Set-PowerPolicy "work-agent-vault-sync"

Write-Host ""
Write-Host "To remove:" -ForegroundColor DarkGray
Write-Host "  schtasks /Delete /TN work-agent-vault-sync /F" -ForegroundColor DarkGray
