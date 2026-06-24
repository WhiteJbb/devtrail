# weekly-distill 안전 실행 wrapper

$RepoRoot = Split-Path $PSScriptRoot -Parent
$LogFile  = "$RepoRoot\logs\weekly.log"

New-Item -ItemType Directory -Force -Path "$RepoRoot\logs" | Out-Null

function Log($msg) {
    $t = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$t  $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Get-EnvVar($key) {
    $envPath = "$RepoRoot\.env"
    if (-not (Test-Path $envPath)) { return $null }
    $line = Get-Content $envPath -Encoding UTF8 |
            Where-Object { $_ -match "^\s*$key\s*=" } |
            Select-Object -First 1
    if (-not $line) { return $null }
    ($line -split "=", 2)[1].Trim().Trim('"').Trim("'")
}

function Send-TelegramAlert($text) {
    $token  = Get-EnvVar "TELEGRAM_BOT_TOKEN"
    $chatId = Get-EnvVar "TELEGRAM_CHAT_ID"
    if (-not $token -or -not $chatId) { return }
    $body      = @{ chat_id = $chatId; text = $text } | ConvertTo-Json -Compress
    $bodyBytes = [System.Text.UTF8Encoding]::new($false).GetBytes($body)
    try {
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
            -Method Post -Body $bodyBytes -ContentType "application/json; charset=utf-8" | Out-Null
    } catch {
        Log "Telegram alert failed: $_"
    }
}

$wa = "$RepoRoot\.venv\Scripts\work-agent.exe"

Log "=== run-weekly-safe start ==="

Set-Location $RepoRoot

try {
    & $wa weekly-distill
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "weekly-distill exit code $LASTEXITCODE"
    }
    Log "=== run-weekly-safe done ==="
} catch {
    $msg = "[work-agent] weekly-distill failed: $($_.Exception.Message)"
    Log "ERROR: $msg"
    Send-TelegramAlert $msg
    exit 1
}
