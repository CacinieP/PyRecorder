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

rem PyRecorder needs Python 3.11+ (pyproject: requires-python) — fail with a
rem clear message instead of a confusing Requires-Python pip error.
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || (
    echo PyRecorder needs Python 3.11+; 'python' on PATH is older. Install it from https://python.org and rerun.
    pause
    exit /b 1
)

if not exist .venv (
    python -m venv .venv
)
.venv\Scripts\python.exe -m pip install -q -e ".[ffmpeg-binary]"

.venv\Scripts\python.exe -m pyrecorder
if errorlevel 1 pause
