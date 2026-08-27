# >>> devtrail activity >>>
# Appends one JSONL line per command to ~/.devtrail/activity/<date>.jsonl.
# ASCII only: $PROFILE encoding varies per machine (cp949 vs utf-8).
# Collection must never break the shell -- everything is wrapped in try/catch.
$global:DevtrailActivityDir = Join-Path $HOME '.devtrail\activity'
if (-not $global:DevtrailActivityWrapped) {
    $global:DevtrailActivityWrapped = $true
    $global:DevtrailActivityLastId = 0
    $__dtPrev = Get-Command prompt -CommandType Function -ErrorAction SilentlyContinue
    $global:DevtrailActivityPrevPrompt = if ($__dtPrev) { $__dtPrev.ScriptBlock } else { $null }

    function global:prompt {
        $__dtOk = $?
        $__dtCode = $LASTEXITCODE
        try {
            $h = Get-History -Count 1 -ErrorAction SilentlyContinue
            if ($h -and $h.Id -ne $global:DevtrailActivityLastId) {
                $global:DevtrailActivityLastId = $h.Id
                $cmd = $h.CommandLine
                if ($cmd) { $cmd = $cmd.Split("`n")[0].Trim() }
                if ($cmd) {
                    $cmd = [regex]::Replace($cmd, '(ghp_|github_pat_|sk-|AIza|xoxb-|Bearer\s+)\S+', '***')
                    $cmd = [regex]::Replace($cmd, '(?i)(token|secret|password|passwd|api_?key)\s*[=:]\s*\S+', '$1=***')
                    $exit = if ($__dtOk) { 0 } elseif ($__dtCode) { $__dtCode } else { 1 }
                    $ts = if ($h.StartExecutionTime) { $h.StartExecutionTime } else { Get-Date }
                    $event = [pscustomobject]@{
                        ts    = $ts.ToString('yyyy-MM-ddTHH:mm:ss')
                        host  = $env:COMPUTERNAME
                        shell = 'pwsh'
                        cwd   = (Get-Location).Path.Replace('\', '/')
                        cmd   = $cmd
                        exit  = $exit
                    }
                    if (-not (Test-Path $global:DevtrailActivityDir)) {
                        New-Item -ItemType Directory -Path $global:DevtrailActivityDir -Force | Out-Null
                    }
                    $file = Join-Path $global:DevtrailActivityDir ($ts.ToString('yyyy-MM-dd') + '.jsonl')
                    Add-Content -Path $file -Value ($event | ConvertTo-Json -Compress) -Encoding utf8
                }
            }
        } catch { }
        $global:LASTEXITCODE = $__dtCode
        if ($global:DevtrailActivityPrevPrompt) {
            & $global:DevtrailActivityPrevPrompt
        } else {
            "PS $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) "
        }
    }
}
# <<< devtrail activity <<<
