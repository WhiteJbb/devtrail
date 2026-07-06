# Vault git sync - local machine variant
# Tracks ALL changes (git add -A) instead of AI folders only
# Use sync-vault.ps1 on the server (AI folders only)

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$LogFile  = "$RepoRoot\logs\sync-vault-local.log"

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

$VaultDir = Get-EnvVar "OBSIDIAN_VAULT_PATH"
if (-not $VaultDir -or -not (Test-Path $VaultDir)) {
    Log "ERROR: OBSIDIAN_VAULT_PATH not set or not found: '$VaultDir'"
    exit 1
}

Set-Location $VaultDir

# Conflict check
if ((Test-Path ".git\MERGE_HEAD") -or (Test-Path ".git\rebase-merge")) {
    $msg = "[vault-local] Conflict detected. Manual fix needed: $VaultDir"
    Log "ERROR: $msg"
    Send-TelegramAlert $msg
    exit 1
}

git fetch origin 2>&1 | ForEach-Object { Log "fetch: $_" }

# Check local changes (all files)
$hasLocal = [bool](git status --porcelain 2>&1)

$localRev  = git rev-parse HEAD
$remoteRev = git rev-parse "@{u}" 2>&1
$hasRemote = ($localRev -ne $remoteRev)

if (-not $hasLocal -and -not $hasRemote) {
    Log "Nothing to sync."
    exit 0
}

Log "=== sync-vault-local start === (local=$hasLocal remote=$hasRemote)"

# Commit all local changes
if ($hasLocal) {
    git add -A 2>&1 | ForEach-Object { Log "add: $_" }
    $commitMsg = "auto: vault sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    git commit -m $commitMsg 2>&1 | ForEach-Object { Log "commit: $_" }
    Log "Committed local changes."
}

# Pull --no-rebase (merge)
if ($hasRemote -or $hasLocal) {
    git pull --no-rebase 2>&1 | ForEach-Object { Log "pull: $_" }

    if ($LASTEXITCODE -ne 0) {
        $msg = "[vault-local] Merge failed. Manual fix needed: $VaultDir"
        Log "ERROR: $msg"
        Send-TelegramAlert $msg
        exit 1
    }

    if ((Test-Path ".git\MERGE_HEAD") -or (Test-Path ".git\rebase-merge")) {
        $msg = "[vault-local] Merge conflict detected. Manual fix needed: $VaultDir"
        Log "ERROR: $msg"
        Send-TelegramAlert $msg
        exit 1
    }
}

# Push (only if local commits exist)
if ($hasLocal) {
    git push 2>&1 | ForEach-Object { Log "push: $_" }

    if ($LASTEXITCODE -ne 0) {
        $msg = "[vault-local] Push failed (exit $LASTEXITCODE)"
        Log "ERROR: $msg"
        Send-TelegramAlert $msg
        exit 1
    }
}

Log "sync-vault-local done"
