@echo off
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [!!] .venv not found. Run install.ps1 first.
    pause
    exit /b 1
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

where wt >nul 2>&1
if %ERRORLEVEL% == 0 (
    wt --title "WORK AGENT" -- cmd /k "chcp 65001 > nul && "%PY%" "%ROOT%start.py""
) else (
    start "WORK AGENT" /MAX cmd /k "chcp 65001 > nul && "%PY%" "%ROOT%start.py""
)
