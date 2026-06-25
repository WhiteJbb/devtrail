# Telegram 봇 상시 실행 wrapper
# 봇이 종료되면 10초 후 자동 재시작

$RepoRoot = Split-Path $PSScriptRoot -Parent
$LogFile  = "$RepoRoot\logs\bot.log"

New-Item -ItemType Directory -Force -Path "$RepoRoot\logs" | Out-Null

function Log($msg) {
    $t = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$t  $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

$wa = "$RepoRoot\.venv\Scripts\work-agent.exe"

if (-not (Test-Path $wa)) {
    Log "ERROR: work-agent.exe not found: $wa"
    exit 1
}

Set-Location $RepoRoot
# editable install이 깨져도 app 패키지를 찾을 수 있게 PYTHONPATH 명시
$env:PYTHONPATH = $RepoRoot

Log "=== bot service start ==="

while ($true) {
    # 업데이트 중이면 완료될 때까지 대기
    while (Test-Path "$RepoRoot\.update.lock") {
        Log "Update in progress, waiting..."
        Start-Sleep 3
    }

    Log "Starting bot..."
    $output = & $wa serve-bot 2>&1
    $code = $LASTEXITCODE
    if ($output) {
        try {
            $output | ForEach-Object {
                $safe = [System.Text.RegularExpressions.Regex]::Replace("$_", "[^\x09\x0A\x0D\x20-\x7E가-힣㄰-㆏]", "?")
                Log "  $safe"
            }
        } catch {
            Log "  [output logging error: $_]"
        }
    }
    Log "Bot exited (code=$code). Restarting in 10s..."
    Start-Sleep 10
}
