param(
    [Parameter(Mandatory)][ValidateSet("morning","evening")][string]$Kind
)

$RepoRoot = Split-Path $PSScriptRoot -Parent
$LogFile  = "$RepoRoot\logs\notify.log"

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
$env:PYTHONPATH = $RepoRoot

Log "notify $Kind ..."
$output = & $wa notify $Kind 2>&1
$code = $LASTEXITCODE
if ($output) {
    $output | ForEach-Object { Log "  $_" }
}
Log "notify $Kind done (code=$code)"
