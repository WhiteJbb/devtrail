# 크로스플랫폼 SessionStart 훅을 호출하는 Windows 진입점입니다.
$ErrorActionPreference = "SilentlyContinue"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if (-not $command) { exit 0 }
    $python = $command.Source
}
$hookPath = Join-Path $repoRoot "scripts\hooks\session-start-briefing.py"

try {
    $payload = [Console]::In.ReadToEnd()
    $previousOutputEncoding = $OutputEncoding
    $previousConsoleEncoding = [Console]::OutputEncoding
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = $utf8
    [Console]::OutputEncoding = $utf8
    $payload | & $python $hookPath 2>$null
} catch {
    exit 0
} finally {
    $OutputEncoding = $previousOutputEncoding
    [Console]::OutputEncoding = $previousConsoleEncoding
}
exit 0
