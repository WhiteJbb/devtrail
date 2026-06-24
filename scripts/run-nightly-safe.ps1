# nightly 안전 실행 wrapper
# update-work-agent → sync-vault(pull) → nightly-distill → push-digest → sync-vault(push)
# 충돌/오류 발생 시 중단 + Telegram 알림

$RepoRoot = Split-Path $PSScriptRoot -Parent
$LogFile  = "$RepoRoot\logs\nightly.log"
$LockFile = "$RepoRoot\.nightly.lock"

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
    $body = @{ chat_id = $chatId; text = $text } | ConvertTo-Json -Compress
    try {
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
            -Method Post -Body $body -ContentType "application/json" | Out-Null
    } catch {
        Log "Telegram alert failed: $_"
    }
}

function Invoke-Step($name, $scriptBlock) {
    Log "--- $name ---"
    try {
        & $scriptBlock
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            throw "exit code $LASTEXITCODE"
        }
        Log "$name OK"
    } catch {
        $msg = "[work-agent] nightly 실패 — $name : $($_.Exception.Message)"
        Log "ERROR: $msg"
        Send-TelegramAlert $msg
        throw
    }
}

# ── 중복 실행 방지 ────────────────────────────────────────────────────
if (Test-Path $LockFile) {
    $created = (Get-Item $LockFile).LastWriteTime
    $age = (Get-Date) - $created
    if ($age.TotalHours -lt 4) {
        Log "Lock exists (created $($age.TotalMinutes.ToString('0'))min ago). Exit."
        exit 0
    }
    Log "Stale lock (over 4h). Removing and continuing."
    Remove-Item $LockFile -Force
}

New-Item -ItemType File -Path $LockFile -Force | Out-Null

$wa = "$RepoRoot\.venv\Scripts\work-agent.exe"

try {
    Log "==============================="
    Log "=== run-nightly-safe start ==="
    Log "==============================="

    # 1. work-agent 코드 업데이트
    Invoke-Step "update-work-agent" {
        & "$RepoRoot\scripts\update-work-agent.ps1"
    }

    # 2. Vault 최신화 (pull)
    Invoke-Step "sync-vault (pull)" {
        & "$RepoRoot\scripts\sync-vault.ps1" -Internal
    }

    # 3. nightly-distill
    Invoke-Step "nightly-distill" {
        Set-Location $RepoRoot
        & $wa nightly-distill
    }

    # 4. push-digest
    Invoke-Step "push-digest" {
        & $wa push-digest --daily
    }

    # 5. 결과 vault에 push
    Invoke-Step "sync-vault (push)" {
        & "$RepoRoot\scripts\sync-vault.ps1" -Internal -CommitMsg "auto: nightly distill $(Get-Date -Format 'yyyy-MM-dd')"
    }

    Log "=== run-nightly-safe done ==="
}
catch {
    Log "=== run-nightly-safe FAILED ==="
    exit 1
}
finally {
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
