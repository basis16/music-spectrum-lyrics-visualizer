@echo off
setlocal EnableDelayedExpansion
title Music Spectrum Lyric Video Maker - Setup
color 0F

echo ============================================================
echo   Music Spectrum Lyric Video Maker - Setup
echo ============================================================
echo.

REM ---- Step 1: Check Python ----
echo [1/4] Checking Python installation...
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do set PYVER=%%V
echo     Found Python !PYVER!
echo.

REM ---- Step 2: Virtual environment ----
echo [2/4] Creating virtual environment (.venv)...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo     Virtual environment created.
) else (
    echo     Virtual environment already exists, skipping.
)
echo.

REM ---- Step 3: Install dependencies ----
echo [3/4] Installing Python dependencies...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 (
    echo.
    echo [WARN] Could not upgrade pip, continuing anyway.
)
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies.
    echo Check your internet connection and try again.
    pause
    exit /b 1
)
echo     Dependencies installed.
echo.

REM ---- Step 4: Check FFmpeg ----
echo [4/4] Checking FFmpeg...
where ffmpeg >nul 2>nul
if errorlevel 1 (
    if exist "app\assets\ffmpeg\ffmpeg.exe" (
        echo     FFmpeg found at app\assets\ffmpeg\ffmpeg.exe
    ) else (
        echo.
        echo [INFO] FFmpeg is not detected on this system.
        echo You can install FFmpeg later from the application
        echo using the "Install FFmpeg Online" button in Settings,
        echo or download manually from: https://www.gyan.dev/ffmpeg/builds/
        echo.
    )
) else (
    echo     FFmpeg detected on PATH.
)
echo.

echo ============================================================
echo   Setup complete. Run run.bat to start the application.
echo ============================================================
echo.
pause
endlocal
