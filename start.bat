@echo off
rem PyRecorder launcher for Windows (double-click in Explorer).
rem Creates a project venv on first run; the [ffmpeg-binary] extra ships a
rem private ffmpeg so no system setup is needed.
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (
    echo Python not found. Install Python 3.11+ from https://python.org first.
    pause
    exit /b 1
)

if not exist .venv (
    python -m venv .venv
)
.venv\Scripts\python.exe -m pip install -q -e ".[ffmpeg-binary]"

.venv\Scripts\python.exe -m pyrecorder
if errorlevel 1 pause
