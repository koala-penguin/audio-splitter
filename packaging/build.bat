@echo off
REM Build a single-file Windows .exe with PyInstaller.
REM Output: dist\AudioSplitter.exe
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
    echo [build] Creating venv...
    py -3.12 -m venv .venv || python -m venv .venv
)

".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
".venv\Scripts\python.exe" -m pip install pyinstaller>=6.0 --quiet

REM Clean prior builds so the spec change always applies.
if exist build rmdir /S /Q build
if exist dist  rmdir /S /Q dist

".venv\Scripts\python.exe" -m PyInstaller packaging\audio_splitter.spec --noconfirm
if errorlevel 1 (
    echo [build] PyInstaller failed.
    exit /b 1
)

echo.
echo [build] Done. See dist\AudioSplitter.exe
endlocal
