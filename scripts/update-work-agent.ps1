# work-agent 코드 자동 업데이트
# 로컬 변경이 있으면 건너뜀. 새 커밋이 있으면 pull.
# pyproject.toml 변경 시에만 pip 재설치 (editable install은 소스 변경 자동 반영)

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

# pyproject.toml 변경 여부 확인 (pull 전에 diff 확인)
$pyprojectChanged = git diff HEAD "$remote" --name-only 2>&1 | Where-Object { $_ -match "pyproject\.toml" }

Log "New commits detected. Pulling..."
git pull --ff-only 2>&1 | ForEach-Object { Log "pull: $_" }

if ($LASTEXITCODE -ne 0) {
    Log "ERROR: git pull failed (exit $LASTEXITCODE)"
    exit 1
}

# editable install이므로 pyproject.toml 변경 시에만 pip 재설치 필요
if (-not $pyprojectChanged) {
    Log "pyproject.toml unchanged — editable install auto-reflects source changes. Done."
    exit 0
}

Log "pyproject.toml changed — reinstalling package..."

# 업데이트 락 생성 — bot service가 재시작을 대기하게 함
Set-Content $LockFile "" -Encoding UTF8
Log "Update lock created."

try {
    # work-agent.exe 프로세스 트리 강제 종료
    Log "Stopping work-agent process tree..."
    taskkill /F /IM work-agent.exe /T 2>&1 | ForEach-Object { Log "taskkill: $_" }
    Start-Sleep -Seconds 3

    # 이전 실패로 남은 pip 임시 디렉터리 정리 (.venv가 있을 때만)
    $sitePackages = "$RepoRoot\.venv\Lib\site-packages"
    if (Test-Path $sitePackages) {
        Get-ChildItem "$sitePackages\~*" -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-Item $_.FullName -Recurse -Force
            Log "Cleaned stale pip temp: $($_.Name)"
        }
    }

    $venvPy = "$RepoRoot\.venv\Scripts\python.exe"
    $pipExe = if (Test-Path $venvPy) { $venvPy } else { (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
    if (-not $pipExe) { Log "ERROR: python.exe를 찾을 수 없습니다"; exit 1 }
    & $pipExe -m pip install -e "$RepoRoot" 2>&1 | ForEach-Object { Log "pip: $_" }
    if ($LASTEXITCODE -ne 0) {
        Log "ERROR: pip install failed (exit $LASTEXITCODE)"
        exit 1
    }

    Log "update-work-agent done"
} finally {
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    Log "Update lock released."
}
