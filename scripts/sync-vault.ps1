# Vault git 동기화
# AI 폴더 변경만 커밋 → pull --rebase → push
# 충돌 감지 시 중단 + Telegram 알림

param(
    [string]$CommitMsg = ""   # 커밋 메시지 직접 지정 (생략 시 자동 생성)
)

$RepoRoot = Split-Path $PSScriptRoot -Parent
$LogFile  = "$RepoRoot\logs\sync-vault.log"
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

# ── nightly 실행 중이면 건너뜀 ────────────────────────────────────────
if (Test-Path $LockFile) {
    Log "Nightly lock active — skip vault sync."
    exit 0
}

# ── Vault 경로 확인 ───────────────────────────────────────────────────
$VaultDir = Get-EnvVar "OBSIDIAN_VAULT_PATH"
if (-not $VaultDir -or -not (Test-Path $VaultDir)) {
    Log "ERROR: OBSIDIAN_VAULT_PATH not set or not found: '$VaultDir'"
    exit 1
}

Log "=== sync-vault start === ($VaultDir)"
Set-Location $VaultDir

# ── 충돌 상태 체크 ────────────────────────────────────────────────────
if ((Test-Path ".git\MERGE_HEAD") -or (Test-Path ".git\rebase-merge")) {
    $msg = "[work-agent] Vault 충돌 상태 감지. 수동 해결 필요: $VaultDir"
    Log "ERROR: $msg"
    Send-TelegramAlert $msg
    exit 1
}

# ── fetch ──────────────────────────────────────────────────────────────
git fetch origin 2>&1 | ForEach-Object { Log "fetch: $_" }

# ── 로컬 변경 커밋 (AI 폴더만) ────────────────────────────────────────
$aiFolders = @("00_Inbox", "10_Worklog", "50_Outputs", "60_Candidates")
$hasChanges = $false

foreach ($folder in $aiFolders) {
    if (Test-Path $folder) {
        $changes = git status --porcelain $folder 2>&1
        if ($changes) { $hasChanges = $true; break }
    }
}

if ($hasChanges) {
    foreach ($folder in $aiFolders) {
        if (Test-Path $folder) {
            git add $folder 2>&1 | ForEach-Object { Log "add: $_" }
        }
    }

    if (-not $CommitMsg) {
        $CommitMsg = "auto: vault sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    }

    git commit -m $CommitMsg 2>&1 | ForEach-Object { Log "commit: $_" }
    Log "Committed local changes."
} else {
    Log "No local changes in AI folders."
}

# ── pull --rebase ──────────────────────────────────────────────────────
git pull --rebase 2>&1 | ForEach-Object { Log "pull: $_" }

if ($LASTEXITCODE -ne 0) {
    $msg = "[work-agent] Vault rebase 실패. 수동 해결 필요: $VaultDir"
    Log "ERROR: $msg"
    Send-TelegramAlert $msg
    # rebase 중단
    git rebase --abort 2>&1 | Out-Null
    exit 1
}

# rebase 후 충돌 상태 재확인
if ((Test-Path ".git\MERGE_HEAD") -or (Test-Path ".git\rebase-merge")) {
    $msg = "[work-agent] Vault rebase 충돌 감지. 수동 해결 필요: $VaultDir"
    Log "ERROR: $msg"
    Send-TelegramAlert $msg
    exit 1
}

# ── push ───────────────────────────────────────────────────────────────
git push 2>&1 | ForEach-Object { Log "push: $_" }

if ($LASTEXITCODE -ne 0) {
    $msg = "[work-agent] Vault push 실패 (exit $LASTEXITCODE)"
    Log "ERROR: $msg"
    Send-TelegramAlert $msg
    exit 1
}

Log "sync-vault done"
