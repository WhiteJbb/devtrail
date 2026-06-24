# Telegram 봇 상시 실행 wrapper
# 봇이 종료되면 10초 후 자동 재시작

$RepoRoot = Split-Path $PSScriptRoot -Parent
$LogFile  = "$RepoRoot\logs\bot.log"

New-Item -ItemType Directory -Force -Path "$RepoRoot\logs" | Out-Null

function Log($msg) {
    $t = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$t  $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

$wa = "$RepoRoot\.venv\Scripts\work-agent.exe"

if (-not (Test-Path $wa)) {
    Log "ERROR: work-agent.exe not found: $wa"
    exit 1
}

Set-Location $RepoRoot

Log "=== bot service start ==="

while ($true) {
    Log "Starting bot..."
    $output = & $wa serve-bot 2>&1
    $code = $LASTEXITCODE
    if ($output) {
        $output | ForEach-Object { Log "  $_" }
    }
    Log "Bot exited (code=$code). Restarting in 10s..."
    Start-Sleep 10
}
