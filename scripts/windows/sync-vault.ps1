# Vault git 동기화
# AI 폴더 변경만 커밋 → pull(merge) → push
# 충돌 감지 시 중단 + Telegram 알림

param(
    [string]$CommitMsg = "",  # 커밋 메시지 직접 지정 (생략 시 자동 생성)
    [switch]$Internal         # nightly에서 호출 시 lock 체크 건너뜀
)

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
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
    $body      = @{ chat_id = $chatId; text = $text } | ConvertTo-Json -Compress
    $bodyBytes = [System.Text.UTF8Encoding]::new($false).GetBytes($body)
    try {
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
            -Method Post -Body $bodyBytes -ContentType "application/json; charset=utf-8" | Out-Null
    } catch {
        Log "Telegram alert failed: $_"
    }
}

# ── nightly 실행 중이면 건너뜀 (직접 호출 시 제외) ───────────────────
if (-not $Internal -and (Test-Path $LockFile)) {
    Log "Nightly lock active — skip vault sync."
    exit 0
}

# ── Vault 경로 확인 ───────────────────────────────────────────────────
$VaultDir = Get-EnvVar "OBSIDIAN_VAULT_PATH"
if (-not $VaultDir -or -not (Test-Path $VaultDir)) {
    Log "ERROR: OBSIDIAN_VAULT_PATH not set or not found: '$VaultDir'"
    exit 1
}

Set-Location $VaultDir

# ── 충돌 상태 체크 ────────────────────────────────────────────────────
if ((Test-Path ".git\MERGE_HEAD") -or (Test-Path ".git\rebase-merge")) {
    $msg = "[devtrail] Vault 충돌 상태 감지. 수동 해결 필요: $VaultDir"
    Log "ERROR: $msg"
    Send-TelegramAlert $msg
    exit 1
}

# ── fetch ──────────────────────────────────────────────────────────────
git fetch origin 2>&1 | ForEach-Object { Log "fetch: $_" }

# ── 로컬 변경 확인 (AI 폴더만) ───────────────────────────────────────
$aiFolders = @("00_Inbox", "10_Worklog", "20_Knowledge", "30_Projects", "50_Outputs", "60_Candidates", "70_Tasks")
$hasLocal = $false
foreach ($folder in $aiFolders) {
    if ((Test-Path $folder) -and (git status --porcelain $folder 2>&1)) {
        $hasLocal = $true; break
    }
}
if (-not $hasLocal -and (Test-Path "log.md") -and (git status --porcelain "log.md" 2>&1)) {
    $hasLocal = $true
}

# ── remote 변경 확인 ──────────────────────────────────────────────────
$localRev  = git rev-parse HEAD
$remoteRev = git rev-parse "@{u}" 2>&1
$hasRemote = ($localRev -ne $remoteRev)

# 둘 다 없으면 조기 종료
if (-not $hasLocal -and -not $hasRemote) {
    Log "Nothing to sync."
    exit 0
}

Log "=== sync-vault start === (local=$hasLocal remote=$hasRemote)"

# ── 로컬 변경 커밋 ────────────────────────────────────────────────────
if ($hasLocal) {
    foreach ($folder in $aiFolders) {
        if (Test-Path $folder) {
            git add $folder 2>&1 | ForEach-Object { Log "add: $_" }
        }
    }
    if (Test-Path "log.md") {
        git add "log.md" 2>&1 | ForEach-Object { Log "add: $_" }
    }
    if (-not $CommitMsg) {
        $CommitMsg = "auto: vault sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    }
    git commit -m $CommitMsg 2>&1 | ForEach-Object { Log "commit: $_" }
    Log "Committed local changes."
}

# ── pull --no-rebase (merge) ───────────────────────────────────────────
# rebase 대신 merge 사용: 노트 파일은 대부분 신규 추가라 충돌이 드물고,
# log.md는 merge=union으로 처리되므로 merge가 더 안전하다.
if ($hasRemote -or $hasLocal) {
    git pull --no-rebase 2>&1 | ForEach-Object { Log "pull: $_" }

    if ($LASTEXITCODE -ne 0) {
        $msg = "[devtrail] Vault merge 실패. 수동 해결 필요: $VaultDir"
        Log "ERROR: $msg"
        Send-TelegramAlert $msg
        exit 1
    }

    if ((Test-Path ".git\MERGE_HEAD") -or (Test-Path ".git\rebase-merge")) {
        $msg = "[devtrail] Vault merge 충돌 감지. 수동 해결 필요: $VaultDir"
        Log "ERROR: $msg"
        Send-TelegramAlert $msg
        exit 1
    }
}

# ── push (로컬 커밋이 있을 때만) ──────────────────────────────────────
if ($hasLocal) {
    git push 2>&1 | ForEach-Object { Log "push: $_" }

    if ($LASTEXITCODE -ne 0) {
        $msg = "[devtrail] Vault push 실패 (exit $LASTEXITCODE)"
        Log "ERROR: $msg"
        Send-TelegramAlert $msg
        exit 1
    }

    # 커밋된 파일 목록 수집해서 알림
    $changed = git diff --name-only HEAD~1 HEAD 2>&1 | Where-Object { $_ -ne "" }
    $count   = ($changed | Measure-Object).Count
    $preview = ($changed | Select-Object -First 5) -join "`n  "
    $more    = if ($count -gt 5) { "`n  ... 외 $($count - 5)개" } else { "" }
    Send-TelegramAlert "📥 Vault 업데이트 ($count개 파일)`n  $preview$more"
}

Log "sync-vault done"
