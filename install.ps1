# work-agent 설치 스크립트
#
# 최초 설치:
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# 새 레포에 훅 추가:
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Repo C:\path\to\myproject
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Repo C:\path\to\myproject -Project myproject

param(
    [string]$Repo    = "",   # 훅을 설치할 레포 경로 (생략 시 훅 설치 건너뜀)
    [string]$Project = ""    # 프로젝트명 (생략 시 레포 폴더명 사용)
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

# ── 출력 헬퍼 ──────────────────────────────────────────────────────────────────

function ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function info($msg) { Write-Host "  --> $msg"  -ForegroundColor Cyan }
function fail($msg) { Write-Host "  [X] $msg"  -ForegroundColor Red; exit 1 }
function step($msg) { Write-Host "`n$msg" -ForegroundColor White }

# ── 1. Python 확인 ────────────────────────────────────────────────────────────

step "[ 1 / 5 ]  Python 확인"

$PyExe = $null

# py launcher가 있으면 설치된 버전 목록을 읽어 3.10+ 중 최신을 선택
# py --list 출력 형식: " -3.14-64"
$pyListRaw = py --list 2>$null | Where-Object { $_ -match "^\s*-3\.\d+" }
if ($pyListRaw) {
    $versions = $pyListRaw |
        ForEach-Object {
            if ($_ -match "-3\.(\d+)") { [int]$Matches[1] }
        } |
        Where-Object { $_ -ge 10 } |
        Sort-Object -Descending

    if ($versions) {
        $best = "3.$($versions[0])"
        $PyExe = (py "-$best" -c "import sys; print(sys.executable)" 2>&1) | Select-Object -First 1
        $PyExe = "$PyExe".Trim()
        ok "Python $best 발견 (py --list)"
    }
}

# py --list 실패 시 순서대로 직접 확인
if (-not $PyExe) {
    foreach ($candidate in @("py -3.14","py -3.13","py -3.12","py -3.11","py -3.10","python")) {
        try {
            $ver = & cmd /c "$candidate --version 2>&1"
            if ($ver -match "Python (3\.1\d+)") {
                $PyExe = & cmd /c "$candidate -c `"import sys; print(sys.executable)`" 2>&1"
                $PyExe = $PyExe.Trim()
                ok "Python $($Matches[1]) 발견 ($candidate)"
                break
            }
        } catch {}
    }
}

if (-not $PyExe) { fail "Python 3.10 이상이 필요합니다. https://python.org 에서 설치 후 다시 실행하세요." }

# ── 2. 가상환경 생성 ──────────────────────────────────────────────────────────

step "[ 2 / 5 ]  가상환경 (.venv)"

$VenvDir    = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"

if (Test-Path $VenvPython) {
    ok ".venv 이미 존재 — 건너뜀"
} else {
    info ".venv 생성 중..."
    & $PyExe -m venv $VenvDir
    ok ".venv 생성 완료"
}

# ── 3. 패키지 설치 ────────────────────────────────────────────────────────────

step "[ 3 / 5 ]  패키지 설치 (pip install -e .)"

$installed = & $VenvPip show work-agent 2>&1
if ($installed -match "Version:") {
    ok "work-agent 이미 설치됨 — 업그레이드 확인 중..."
}

& $VenvPip install -e $Root -q
if ($LASTEXITCODE -ne 0) { fail "pip install 실패" }
ok "설치 완료"

# ── 4. PATH 등록 ──────────────────────────────────────────────────────────────

step "[ 4 / 5 ]  PATH 등록"

$ScriptsDir = Join-Path $VenvDir "Scripts"
$userPath   = [Environment]::GetEnvironmentVariable("PATH", "User")

if ($userPath -split ";" | Where-Object { $_ -eq $ScriptsDir }) {
    ok "이미 PATH에 등록되어 있음"
} else {
    $newPath = ($userPath.TrimEnd(";") + ";" + $ScriptsDir)
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    ok "PATH에 추가됨: $ScriptsDir"
    warn "새 터미널을 열어야 work-agent 명령이 인식됩니다."
}

# ── 5. .env 초기화 ────────────────────────────────────────────────────────────

step "[ 5 / 5 ]  .env 설정"

$EnvFile    = Join-Path $Root ".env"
$EnvExample = Join-Path $Root ".env.example"

if (Test-Path $EnvFile) {
    ok ".env 이미 존재"
} elseif (Test-Path $EnvExample) {
    Copy-Item $EnvExample $EnvFile
    ok ".env.example → .env 복사 완료"
    warn "아래 항목을 .env에서 직접 수정하세요:"
    warn "  OBSIDIAN_VAULT_PATH = Obsidian Vault 경로"
    warn "  WRITER_PROVIDER     = gemini / openai / ollama 중 택1"
    warn "  GEMINI_API_KEY      = (gemini 사용 시)"
} else {
    warn ".env.example 없음 — .env를 직접 생성하세요."
}

# ── 훅 설치 (선택) ────────────────────────────────────────────────────────────

if ($Repo -ne "") {
    Write-Host ""
    Write-Host "[ 훅 설치 ]  $Repo" -ForegroundColor White

    $RepoPath = Resolve-Path $Repo -ErrorAction SilentlyContinue
    if (-not $RepoPath) { fail "레포 경로를 찾을 수 없습니다: $Repo" }

    if (-not (Test-Path (Join-Path $RepoPath ".git"))) {
        fail "$RepoPath 는 git 레포지토리가 아닙니다."
    }

    $WorkAgentExe = Join-Path $ScriptsDir "work-agent.exe"
    if (-not (Test-Path $WorkAgentExe)) { fail "work-agent.exe를 찾을 수 없습니다: $WorkAgentExe" }

    $projectName = if ($Project) { $Project } else { Split-Path $RepoPath -Leaf }
    info "프로젝트명: $projectName"

    & $WorkAgentExe install-hooks $RepoPath --project $projectName --force
    if ($LASTEXITCODE -ne 0) { fail "훅 설치 실패" }
}

# ── 완료 ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host "  설치 완료!" -ForegroundColor Green
Write-Host ""
Write-Host "  다음 단계:" -ForegroundColor White
if (-not (Test-Path $EnvFile) -or ((Get-Content $EnvFile -Raw) -match "OBSIDIAN_VAULT_PATH\s*=\s*$")) {
    Write-Host "    1. .env 파일에서 OBSIDIAN_VAULT_PATH 설정" -ForegroundColor Yellow
    Write-Host "    2. 새 터미널 열기"
    Write-Host "    3. python start.py  (대시보드)"
    Write-Host ""
    Write-Host "  다른 레포에 훅 추가하려면:" -ForegroundColor DarkGray
    Write-Host "    powershell -ExecutionPolicy Bypass -File install.ps1 -Repo C:\path\to\repo" -ForegroundColor DarkGray
} else {
    Write-Host "    1. 새 터미널 열기"
    Write-Host "    2. python start.py  (대시보드)"
    Write-Host ""
    Write-Host "  다른 레포에 훅 추가하려면:" -ForegroundColor DarkGray
    Write-Host "    powershell -ExecutionPolicy Bypass -File install.ps1 -Repo C:\path\to\repo" -ForegroundColor DarkGray
}
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
Write-Host ""
