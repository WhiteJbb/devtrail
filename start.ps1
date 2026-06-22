# work-agent 실행환경 시작 스크립트
# 실행: powershell -ExecutionPolicy Bypass -File start.ps1

$ErrorActionPreference = "Stop"
$PYTHON = "C:\Users\User\AppData\Local\Programs\Python\Python310\python.exe"
$OLLAMA = "C:\Users\User\AppData\Local\Programs\Ollama\ollama.exe"
$PROJECT = "C:\Users\User\git\work-agent"
$ENV_FILE = Join-Path $PROJECT ".env"

# ── 색상 출력 헬퍼 ────────────────────────────────────────────────────────────
function Ok($msg)   { Write-Host "  [OK] $msg"   -ForegroundColor Green }
function Warn($msg) { Write-Host "  [!!] $msg"   -ForegroundColor Yellow }
function Info($msg) { Write-Host "  --> $msg"    -ForegroundColor Cyan }
function Fail($msg) { Write-Host "  [X] $msg"    -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "  work-agent  |  제2의 세컨드브레인 실행환경"          -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. 프로젝트 디렉토리 확인 ─────────────────────────────────────────────────
if (-not (Test-Path $PROJECT)) { Fail "프로젝트 디렉토리 없음: $PROJECT" }
Set-Location $PROJECT

# ── 2. .env 파일 확인 ─────────────────────────────────────────────────────────
if (-not (Test-Path $ENV_FILE)) {
    Warn ".env 파일 없음. .env.example을 복사한 뒤 설정하세요."
} else {
    Ok ".env 확인"
}

# ── 3. Python 확인 ────────────────────────────────────────────────────────────
if (-not (Test-Path $PYTHON)) { Fail "Python 없음: $PYTHON" }
$pyver = & $PYTHON --version 2>&1
Ok "Python: $pyver"

# ── 4. 필수 패키지 확인 ───────────────────────────────────────────────────────
$import_check = & $PYTHON -c "import typer, pydantic, frontmatter, httpx" 2>&1
if ($LASTEXITCODE -ne 0) {
    Warn "패키지 누락 감지 — pip install 실행 중..."
    & $PYTHON -m pip install -e "$PROJECT" -q
    if ($LASTEXITCODE -ne 0) { Fail "패키지 설치 실패. pip install -e . 를 수동으로 실행하세요." }
    Ok "패키지 설치 완료"
} else {
    Ok "패키지 정상"
}

# ── 5. Ollama 상태 확인 및 시작 ───────────────────────────────────────────────
$ollamaRunning = $false
try {
    $response = Invoke-WebRequest -Uri "http://localhost:11434/" -TimeoutSec 2 -ErrorAction Stop
    $ollamaRunning = $true
} catch {}

if ($ollamaRunning) {
    Ok "Ollama 이미 실행 중 (localhost:11434)"
} else {
    if (-not (Test-Path $OLLAMA)) {
        Warn "Ollama 실행파일 없음: $OLLAMA"
        Warn "Ollama가 설치되어 있으면 먼저 실행하세요."
    } else {
        Info "Ollama 시작 중..."
        Start-Process -FilePath $OLLAMA -WindowStyle Hidden
        # 최대 10초 대기
        $waited = 0
        while ($waited -lt 10) {
            Start-Sleep -Seconds 1
            $waited++
            try {
                Invoke-WebRequest -Uri "http://localhost:11434/" -TimeoutSec 1 -ErrorAction Stop | Out-Null
                $ollamaRunning = $true
                break
            } catch {}
        }
        if ($ollamaRunning) { Ok "Ollama 시작 완료" }
        else { Warn "Ollama 응답 없음 — 수동으로 확인하세요." }
    }
}

# ── 6. Ollama 모델 확인 ───────────────────────────────────────────────────────
if ($ollamaRunning) {
    # .env에서 OLLAMA_MODEL 읽기
    $model = "qwen2.5:14b-instruct-q4_K_M"
    if (Test-Path $ENV_FILE) {
        $line = Get-Content $ENV_FILE | Where-Object { $_ -match "^OLLAMA_MODEL=" }
        if ($line) { $model = $line -replace "^OLLAMA_MODEL=", "" }
    }
    $modelList = & $OLLAMA list 2>&1
    if ($modelList -match [regex]::Escape($model.Split(":")[0])) {
        Ok "모델 확인: $model"
    } else {
        Warn "모델 '$model' 없음 — ollama pull $model 필요"
    }
}

# ── 7. Obsidian Vault 확인 ────────────────────────────────────────────────────
$vault = "D:\personal-vault"
if (Test-Path $ENV_FILE) {
    $vaultLine = Get-Content $ENV_FILE | Where-Object { $_ -match "^OBSIDIAN_VAULT_DIR=" }
    if ($vaultLine) { $vault = $vaultLine -replace "^OBSIDIAN_VAULT_DIR=", "" }
}
if (Test-Path $vault) {
    $wikiPath = Join-Path $vault "60_Wiki"
    $wikiCount = 0
    if (Test-Path $wikiPath) { $wikiCount = (Get-ChildItem $wikiPath -Filter "*.md" -Recurse).Count }
    Ok "Vault: $vault  |  Wiki 페이지: $wikiCount 개"
} else {
    Warn "Vault 경로 없음: $vault"
}

# ── 8. Telegram 봇 시작 ───────────────────────────────────────────────────────
$botAlreadyRunning = Get-Process -Name "python*" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*serve-bot*" } 2>$null

if ($botAlreadyRunning) {
    Ok "Telegram 봇 이미 실행 중 (PID: $($botAlreadyRunning.Id))"
} else {
    Info "Telegram 봇 시작 중..."
    $botArgs = "-NoExit -Command `"Set-Location '$PROJECT'; & '$PYTHON' -m app.cli serve-bot`""
    Start-Process powershell -ArgumentList $botArgs -WindowStyle Normal
    Start-Sleep -Seconds 2
    Ok "Telegram 봇 시작 (별도 창에서 실행)"
}

# ── 9. 상태 요약 ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "  실행 완료 — 사용 가능한 명령어"                      -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  # CLI 직접 실행 (이 창에서)" -ForegroundColor White
Write-Host "  cd $PROJECT" -ForegroundColor DarkGray
Write-Host "  & '$PYTHON' -m app.cli suggest-topics" -ForegroundColor DarkGray
Write-Host "  & '$PYTHON' -m app.cli write-draft 'RAG 파이프라인'" -ForegroundColor DarkGray
Write-Host "  & '$PYTHON' -m app.cli wiki-query 'vLLM 설정 방법'" -ForegroundColor DarkGray
Write-Host "  & '$PYTHON' -m app.cli wiki-ingest --folder 50_Reference/AI" -ForegroundColor DarkGray
Write-Host "  & '$PYTHON' -m app.cli ask '오늘 작업 회고 정리해줘'" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  # Telegram 봇 (원격)" -ForegroundColor White
Write-Host "  /suggest, /worklog, /todo, /portfolio, /resume" -ForegroundColor DarkGray
Write-Host "  자연어: '오늘 작업 정리해줘', 'vLLM 셧다운 원인 알려줘'" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  # Obsidian Wiki" -ForegroundColor White
Write-Host "  Vault: $vault\60_Wiki" -ForegroundColor DarkGray
Write-Host ""
