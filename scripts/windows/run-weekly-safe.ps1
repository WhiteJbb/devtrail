# weekly-distill 안전 실행 wrapper

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
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

$venvWa = "$RepoRoot\.venv\Scripts\devtrail.exe"
$wa = if (Test-Path $venvWa) { $venvWa } else { (Get-Command devtrail.exe -ErrorAction SilentlyContinue).Source }
if (-not $wa) { Log "devtrail.exe를 찾을 수 없습니다 (.venv 없고 PATH에도 없음)."; exit 1 }
$LockFile = "$RepoRoot\.weekly.lock"

# 중복 실행 방지
if (Test-Path $LockFile) {
    $age = (Get-Date) - (Get-Item $LockFile).LastWriteTime
    if ($age.TotalHours -lt 4) {
        Log "Lock exists ($($age.TotalMinutes.ToString('0'))min ago). Exit."
        exit 0
    }
    Log "Stale lock (over 4h). Removing and continuing."
    Remove-Item $LockFile -Force
}

New-Item -ItemType File -Path $LockFile -Force | Out-Null

Log "=== run-weekly-safe start ==="

Set-Location $RepoRoot

try {
    & $wa weekly-distill
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "weekly-distill exit code $LASTEXITCODE"
    }
    Log "=== run-weekly-safe done ==="
} catch {
    $msg = "[devtrail] weekly-distill failed: $($_.Exception.Message)"
    Log "ERROR: $msg"
    Send-TelegramAlert $msg
    exit 1
} finally {
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
