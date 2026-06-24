# work-agent 코드 자동 업데이트
# 로컬 변경이 있으면 건너뜀. 새 커밋이 있으면 pull + 재설치.

$RepoRoot  = Split-Path $PSScriptRoot -Parent
$LogFile   = "$RepoRoot\logs\update-work-agent.log"
$LockFile  = "$RepoRoot\.update.lock"

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

# 업데이트 락 생성 — bot service가 재시작을 대기하게 함
Set-Content $LockFile "" -Encoding UTF8
Log "Update lock created."

try {
    # 봇 프로세스 종료 (work-agent.exe 점유 해제)
    $botProc = Get-Process -Name "work-agent" -ErrorAction SilentlyContinue
    if ($botProc) {
        Log "Stopping bot process before reinstall..."
        $botProc | Stop-Process -Force
        # 프로세스 완전 종료 대기 (최대 10초)
        $botProc | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
        Log "Bot process stopped."
    }

    # 이전 실패로 남은 pip 임시 디렉터리 정리 (~로 시작하는 invalid distribution)
    $sitePackages = "$RepoRoot\.venv\Lib\site-packages"
    Get-ChildItem "$sitePackages\~*" -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force
        Log "Cleaned stale pip temp: $($_.Name)"
    }

    Log "Reinstalling package..."
    & "$RepoRoot\.venv\Scripts\python.exe" -m pip install -e "$RepoRoot" 2>&1 | ForEach-Object { Log "pip: $_" }
    if ($LASTEXITCODE -ne 0) {
        Log "ERROR: pip install failed (exit $LASTEXITCODE)"
        exit 1
    }

    Log "update-work-agent done"
} finally {
    # 성공·실패 무관하게 락 해제 — bot service 재시작 허용
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    Log "Update lock released."
}
