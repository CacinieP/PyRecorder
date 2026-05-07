@echo off
setlocal enabledelayedexpansion

title PyRecorder - Windows Screen Recorder

:: Set color
color 0A

cls
echo.
echo ===============================================================
echo              PyRecorder - Windows Screen Recorder
echo                       Version 2.0.0
echo                       MIT License
echo ===============================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] Python not found. Please install Python 3.8 or higher
    echo         Download: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: Show Python version
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PY_VERSION=%%i
echo [OK] Python %PY_VERSION% installed
echo.

:: Check if pip is available
pip --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] pip not available. Please reinstall Python with pip
    echo.
    pause
    exit /b 1
)
echo [OK] pip ready
echo.
echo ---------------------------------------------------------------
echo.

:: Main menu
:menu
color 0A
echo Select version to run:
echo.
echo   [1] Basic (Screen recording only)
echo   [2] Pro   (Screen + Audio + Webcam + Window capture)
echo   [3] Install/Update dependencies
echo   [4] Project info
echo   [0] Exit
echo.
echo ---------------------------------------------------------------
echo.

set /p choice="Enter option [0-4]: "

if "%choice%"=="1" goto basic
if "%choice%"=="2" goto pro
if "%choice%"=="3" goto install
if "%choice%"=="4" goto info
if "%choice%"=="0" goto exit
goto menu

:basic
echo.
echo ---------------------------------------------------------------
echo.
echo [OK] Starting Basic version...
echo.
python screen_recorder.py
if errorlevel 1 (
    color 0C
    echo.
    echo [ERROR] Program failed. Make sure dependencies are installed
    echo         Run option [3] to install dependencies
)
goto end

:pro
echo.
echo ---------------------------------------------------------------
echo.
echo [OK] Starting Pro version...
echo.
python screen_recorder_pro.py
if errorlevel 1 (
    color 0C
    echo.
    echo [ERROR] Program failed. Make sure dependencies are installed
    echo         Run option [3] to install dependencies
)
goto end

:install
cls
color 0E
echo.
echo ================================================================
echo              Installing/Updating Dependencies
echo ================================================================
echo.
echo Installing dependencies, please wait...
echo.

:: Install basic dependencies
echo [1/2] Installing basic dependencies...
pip install PyQt6 mss opencv-python numpy Pillow --prefer-binary
if errorlevel 1 (
    color 0C
    echo.
    echo [ERROR] Failed to install dependencies!
    goto end
)
echo [OK] Basic dependencies installed
echo.

:: Install Pro dependencies
echo [2/2] Installing Pro dependencies...
pip install pyaudio moviepy --prefer-binary
if errorlevel 1 (
    color 0C
    echo.
    echo [WARNING] Pro dependencies failed. Basic version will work.
)
echo [OK] Pro dependencies installed
echo.

color 0A
echo ---------------------------------------------------------------
echo.
echo [OK] All dependencies installed!
echo.
pause
cls
goto menu

:info
cls
color 0B
echo.
echo ================================================================
echo              Project Information
echo ================================================================
echo.
echo Project: PyRecorder
echo Version : 2.0.0
echo License : MIT License
echo.
echo Features:
echo   - Full screen or custom region recording
echo   - Adjustable frame rate (10-60 FPS)
echo   - Multiple video codec support
echo   - Pro version with audio recording
echo   - Webcam picture-in-picture overlay (teaching mode)
echo   - Window capture (select specific application window)
echo   - 4 overlay positions, adjustable size
echo   - Live webcam preview
echo   - Real-time recording preview
echo.
echo GitHub: https://github.com/CacinieP/PyRecorder
echo.
echo ---------------------------------------------------------------
echo.
pause
cls
goto menu

:exit
cls
color 07
echo.
echo Thank you for using PyRecorder!
echo.
timeout /t 2 >nul
exit /b 0

:end
echo.
echo ---------------------------------------------------------------
echo.
pause
cls
goto menu
