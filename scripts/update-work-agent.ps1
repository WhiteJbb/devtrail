# work-agent 코드 자동 업데이트
# 로컬 변경이 있으면 건너뜀. 새 커밋이 있으면 pull + 재설치.

$RepoRoot = Split-Path $PSScriptRoot -Parent
$LogFile  = "$RepoRoot\logs\update-work-agent.log"

New-Item -ItemType Directory -Force -Path "$RepoRoot\logs" | Out-Null

function Log($msg) {
    $t = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$t  $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Log "=== update-work-agent start ==="

Set-Location $RepoRoot

# 로컬 수정이 있으면 자동 pull 금지
$dirty = git status --porcelain 2>&1
if ($dirty) {
    Log "Local changes detected — skip auto update."
    $dirty | ForEach-Object { Log "  $_" }
    exit 0
}

git fetch origin 2>&1 | ForEach-Object { Log "fetch: $_" }

$local  = git rev-parse HEAD
$remote = git rev-parse "@{u}" 2>&1

if ($local -eq $remote) {
    Log "Already up to date."
    exit 0
}

Log "New commits detected. Pulling..."
git pull --ff-only 2>&1 | ForEach-Object { Log "pull: $_" }

if ($LASTEXITCODE -ne 0) {
    Log "ERROR: git pull failed (exit $LASTEXITCODE)"
    exit 1
}

Log "Reinstalling package..."
& "$RepoRoot\.venv\Scripts\python.exe" -m pip install -e "$RepoRoot" 2>&1 | ForEach-Object { Log "pip: $_" }
if ($LASTEXITCODE -ne 0) {
    Log "ERROR: pip install failed (exit $LASTEXITCODE)"
    exit 1
}

# 봇 프로세스 재시작 (run-bot-service.ps1이 10초 후 새 코드로 자동 재기동)
$botProc = Get-Process -Name "work-agent" -ErrorAction SilentlyContinue
if ($botProc) {
    Log "Restarting bot process to apply new code..."
    $botProc | Stop-Process -Force
    Log "Bot process stopped. run-bot-service will restart it."
}

Log "update-work-agent done"
