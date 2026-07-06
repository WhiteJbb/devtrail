# nightly 안전 실행 wrapper
# update-devtrail → sync-vault(pull) → nightly-distill → push-digest → sync-vault(push)
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
    $body      = @{ chat_id = $chatId; text = $text } | ConvertTo-Json -Compress
    $bodyBytes = [System.Text.UTF8Encoding]::new($false).GetBytes($body)
    try {
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
            -Method Post -Body $bodyBytes -ContentType "application/json; charset=utf-8" | Out-Null
    } catch {
        Log "Telegram alert failed: $_"
    }
}

function Invoke-Step($name, $scriptBlock) {
    Log "--- $name ---"
    try {
        $output = & $scriptBlock 2>&1
        $exitCode = $LASTEXITCODE
        if ($output) {
            foreach ($line in ($output | Out-String).Trim().Split("`n")) {
                if ($line.Trim()) { Log "  $($line.Trim())" }
            }
        }
        if ($exitCode -and $exitCode -ne 0) {
            throw "exit code $exitCode"
        }
        Log "$name OK"
    } catch {
        $msg = "[devtrail] nightly 실패 — $name : $($_.Exception.Message)"
        Log "ERROR: $msg"
        Send-TelegramAlert $msg
        throw
    }
}

# ── weekly 실행 중이면 대기 ──────────────────────────────────────────
$weeklyLock = "$RepoRoot\.weekly.lock"
if (Test-Path $weeklyLock) {
    $age = (Get-Date) - (Get-Item $weeklyLock).LastWriteTime
    if ($age.TotalHours -lt 4) {
        Log "Weekly distill 실행 중 ($($age.TotalMinutes.ToString('0'))min). 완료까지 대기..."
        $waited = 0
        while ((Test-Path $weeklyLock) -and $waited -lt 60) {
            Start-Sleep 60
            $waited++
        }
        if (Test-Path $weeklyLock) {
            Log "WARNING: Weekly lock 60분 초과. 강제 진행."
        } else {
            Log "Weekly 완료 확인. Nightly 시작."
        }
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

$venvWa = "$RepoRoot\.venv\Scripts\devtrail.exe"
$wa = if (Test-Path $venvWa) { $venvWa } else { (Get-Command devtrail.exe -ErrorAction SilentlyContinue).Source }
if (-not $wa) { Log "devtrail.exe를 찾을 수 없습니다 (.venv 없고 PATH에도 없음)."; exit 1 }

try {
    Log "==============================="
    Log "=== run-nightly-safe start ==="
    Log "==============================="

    # 1. devtrail 코드 업데이트
    Invoke-Step "update-devtrail" {
        & "$RepoRoot\scripts\update-devtrail.ps1"
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
