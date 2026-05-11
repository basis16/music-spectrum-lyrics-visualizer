@echo off
setlocal EnableDelayedExpansion
title Music Spectrum Lyric Video Maker
color 0F

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [ERROR] Virtual environment not found.
    echo Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

python -m app.main
if errorlevel 1 (
    echo.
    echo [ERROR] Application exited with an error.
    echo See the log panel inside the app or the logs\ folder for details.
    echo.
    pause
    exit /b 1
)

endlocal
