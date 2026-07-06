# devtrail 실행환경 시작 스크립트
# 실행: powershell -ExecutionPolicy Bypass -File start.ps1

$ErrorActionPreference = "SilentlyContinue"

$PROJECT  = $PSScriptRoot
$ENV_FILE = Join-Path $PROJECT ".env"

# Python: .venv 우선, 없으면 PATH에서 탐색
$VENV_PYTHON = Join-Path $PROJECT ".venv\Scripts\python.exe"
if (Test-Path $VENV_PYTHON) {
    $PYTHON = $VENV_PYTHON
} else {
    $PYTHON = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PYTHON) { $PYTHON = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
}

# Ollama: LOCALAPPDATA 기준
$OLLAMA = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"

# ── 색상 출력 헬퍼 ────────────────────────────────────────────────────────────
function Ok($msg)     { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn($msg)   { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Info($msg)   { Write-Host "  --> $msg"  -ForegroundColor Cyan }
function Fail($msg)   { Write-Host "  [X]  $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  devtrail  |  Obsidian LLM Wiki Core"               -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. 프로젝트 디렉토리 ──────────────────────────────────────────────────────
Set-Location $PROJECT
Ok "Project: $PROJECT"

# ── 2. .env 확인 ──────────────────────────────────────────────────────────────
function Read-Env {
    $env = @{}
    if (Test-Path $ENV_FILE) {
        Get-Content $ENV_FILE | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#") -and $line -match "=") {
                $k, $v = $line -split "=", 2
                $env[$k.Trim()] = $v.Trim()
            }
        }
    }
    return $env
}

$env_vars = Read-Env
if (-not (Test-Path $ENV_FILE)) {
    Warn ".env 없음 — .env.example 복사 후 설정하세요"
} else {
    Ok ".env 확인"
}

# ── 3. Python 확인 ────────────────────────────────────────────────────────────
if (-not $PYTHON -or -not (Test-Path $PYTHON)) {
    Fail "Python 없음 — .venv 생성 또는 PATH 확인 필요"
}
$pyver = & $PYTHON --version 2>&1
Ok "Python: $pyver  ($PYTHON)"

# ── 4. 패키지 확인 ────────────────────────────────────────────────────────────
& $PYTHON -c "import typer, pydantic, frontmatter, httpx" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Warn "패키지 누락 — pip install 실행 중..."
    & $PYTHON -m pip install -e "$PROJECT" -q
    if ($LASTEXITCODE -ne 0) { Fail "패키지 설치 실패. pip install -e . 수동 실행 필요" }
    Ok "패키지 설치 완료"
} else {
    Ok "패키지 정상"
}

# ── 5. Ollama 상태 확인 ───────────────────────────────────────────────────────
$ollamaRunning = $false
try {
    Invoke-WebRequest -Uri "http://localhost:11434/" -TimeoutSec 2 -ErrorAction Stop | Out-Null
    $ollamaRunning = $true
} catch {}

if ($ollamaRunning) {
    Ok "Ollama 실행 중 (localhost:11434)"
} elseif (Test-Path $OLLAMA) {
    Info "Ollama 시작 중..."
    Start-Process -FilePath $OLLAMA -WindowStyle Hidden
    $waited = 0
    while ($waited -lt 10) {
        Start-Sleep -Seconds 1; $waited++
        try {
            Invoke-WebRequest -Uri "http://localhost:11434/" -TimeoutSec 1 -ErrorAction Stop | Out-Null
            $ollamaRunning = $true; break
        } catch {}
    }
    if ($ollamaRunning) { Ok "Ollama 시작 완료" }
    else { Warn "Ollama 응답 없음 — 수동 확인 필요" }
} else {
    Warn "Ollama 없음: $OLLAMA"
}

# ── 6. 로컬 모델 확인 ─────────────────────────────────────────────────────────
if ($ollamaRunning) {
    $model = if ($env_vars["OLLAMA_MODEL"]) { $env_vars["OLLAMA_MODEL"] } else { "qwen3:8b" }
    $modelList = & $OLLAMA list 2>&1
    $base = $model.Split(":")[0]
    if ($modelList -match [regex]::Escape($base)) {
        Ok "로컬 모델: $model"
    } else {
        Warn "모델 '$model' 없음 — 실행: ollama pull $model"
    }
}

# ── 7. Gemini 설정 확인 ───────────────────────────────────────────────────────
$geminiKey  = $env_vars["GEMINI_API_KEY"]
$writerProv = $env_vars["WRITER_PROVIDER"]
$flashModel = if ($env_vars["GEMINI_FLASH_MODEL"]) { $env_vars["GEMINI_FLASH_MODEL"] } else { "gemini-2.5-flash" }

if ($writerProv -eq "gemini" -and $geminiKey) {
    Ok "Writer: Gemini ($flashModel)"
} elseif ($writerProv -eq "gemini" -and -not $geminiKey) {
    Warn "WRITER_PROVIDER=gemini 이지만 GEMINI_API_KEY 미설정 — 글쓰기 명령 동작 안 함"
} else {
    Info "Writer: $(if ($writerProv) { $writerProv } else { '(미설정)' })"
}

# ── 8. Obsidian Vault 확인 ────────────────────────────────────────────────────
$vaultPath = if ($env_vars["OBSIDIAN_VAULT_PATH"]) { $env_vars["OBSIDIAN_VAULT_PATH"] }
             elseif ($env_vars["OBSIDIAN_VAULT_DIR"]) { $env_vars["OBSIDIAN_VAULT_DIR"] }
             else { "" }

if ($vaultPath -and (Test-Path $vaultPath)) {
    # raw 기록 수
    $rawCount = @(
        Get-ChildItem (Join-Path $vaultPath "00_Inbox") -Filter "*.md" -Recurse -ErrorAction SilentlyContinue
        Get-ChildItem (Join-Path $vaultPath "10_Worklog") -Filter "*.md" -Recurse -ErrorAction SilentlyContinue
    ).Count

    $candidatePath = Join-Path $vaultPath "60_Candidates"
    $candidateCount = if (Test-Path $candidatePath) {
        (Get-ChildItem $candidatePath -Filter "*.md" -Recurse -ErrorAction SilentlyContinue).Count
    } else { 0 }

    $knowledgePath = Join-Path $vaultPath "20_Knowledge"
    $knowledgeCount = if (Test-Path $knowledgePath) {
        (Get-ChildItem $knowledgePath -Filter "*.md" -Recurse -ErrorAction SilentlyContinue).Count
    } else { 0 }

    Ok "Vault: $vaultPath"
    Write-Host "       raw 기록: ${rawCount}개  |  후보 대기: ${candidateCount}개  |  지식: ${knowledgeCount}개" -ForegroundColor DarkGray

    if ($rawCount -gt 0 -and $candidateCount -eq 0) {
        Info "raw 기록 ${rawCount}개 → distill-today 실행 권장"
    } elseif ($candidateCount -gt 0) {
        Info "후보 ${candidateCount}개 대기 중 → list-candidates 로 검토 권장"
    }
} elseif ($vaultPath) {
    Warn "Vault 없음: $vaultPath — init-vault 실행 권장"
} else {
    Warn "OBSIDIAN_VAULT_PATH 미설정 — .env에서 경로를 지정하세요"
}

# ── 9. Telegram 봇 시작 ───────────────────────────────────────────────────────
$messenger = $env_vars["MESSENGER_PROVIDER"]
if ($messenger -eq "telegram") {
    $botProc = Get-WmiObject Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
               Where-Object { $_.CommandLine -like "*serve-bot*" }

    if ($botProc) {
        Ok "Telegram 봇 이미 실행 중 (PID: $($botProc.ProcessId))"
    } else {
        Info "Telegram 봇 시작 중..."
        $botArgs = "-NoExit -Command `"Set-Location '$PROJECT'; & '$PYTHON' -m app.cli serve-bot`""
        Start-Process powershell -ArgumentList $botArgs -WindowStyle Normal
        Start-Sleep -Seconds 2
        Ok "Telegram 봇 시작 (별도 창)"
    }
} else {
    Info "Telegram 봇 비활성 (MESSENGER_PROVIDER 미설정)"
}

# ── 10. 사용 안내 ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  실행 완료 — 사용 가능한 명령어"                        -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "  [Vault 설정]" -ForegroundColor White
Write-Host "    $PYTHON -m app.cli init-vault" -ForegroundColor DarkGray
Write-Host "    $PYTHON -m app.cli install-hooks --repo <레포> --project <프로젝트명>" -ForegroundColor DarkGray
Write-Host ""

Write-Host "  [지식 순환 파이프라인]" -ForegroundColor White
Write-Host "    $PYTHON -m app.cli capture '오늘 작업 내용' --project Devtrail" -ForegroundColor DarkGray
Write-Host "    $PYTHON -m app.cli capture-session --project Devtrail --from-repo" -ForegroundColor DarkGray
Write-Host "    $PYTHON -m app.cli distill-today" -ForegroundColor DarkGray
Write-Host "    $PYTHON -m app.cli list-candidates" -ForegroundColor DarkGray
Write-Host "    $PYTHON -m app.cli promote-candidate '60_Candidates/Knowledge/...'" -ForegroundColor DarkGray
Write-Host ""

Write-Host "  [검색 / Wiki]" -ForegroundColor White
Write-Host "    $PYTHON -m app.cli search 'RAG 검색'" -ForegroundColor DarkGray
Write-Host "    $PYTHON -m app.cli wiki-ingest" -ForegroundColor DarkGray
Write-Host "    $PYTHON -m app.cli wiki-query 'vLLM 설정 방법'" -ForegroundColor DarkGray
Write-Host "    $PYTHON -m app.cli build-context 'XCoreChat 개발환경 분리'" -ForegroundColor DarkGray
Write-Host ""

Write-Host "  [글쓰기]" -ForegroundColor White
Write-Host "    $PYTHON -m app.cli write-blog 'XCoreChat RAG 전략'" -ForegroundColor DarkGray
Write-Host "    $PYTHON -m app.cli summarize-project XCoreChat" -ForegroundColor DarkGray
Write-Host "    $PYTHON -m app.cli interview-questions XCoreChat" -ForegroundColor DarkGray
Write-Host ""

Write-Host "  [자연어]" -ForegroundColor White
Write-Host "    $PYTHON -m app.cli ask '오늘 작업 세션 정리해줘'" -ForegroundColor DarkGray
Write-Host ""

if ($messenger -eq "telegram") {
    Write-Host "  [Telegram]" -ForegroundColor White
    Write-Host "    /capture <메모>   /search <검색어>   /distill" -ForegroundColor DarkGray
    Write-Host "    /context <주제>   /candidates        /draft <주제>" -ForegroundColor DarkGray
    Write-Host "    /session <프로젝트>   /worklog   /todo" -ForegroundColor DarkGray
    Write-Host ""
}
