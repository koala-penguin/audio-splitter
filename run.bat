@echo off
REM One-click launcher for Windows. Re-runs setup if .venv is missing.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    py -3.12 -m venv .venv
    if errorlevel 1 (
        python -m venv .venv
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
".venv\Scripts\python.exe" -m audio_splitter
endlocal
