@echo off
REM ============================================================
REM  Music Spectrum Lyrics Visualizer  -  Windows runner
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Folder venv belum ada.
    echo         Jalankan setup.bat terlebih dulu.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Gagal mengaktifkan venv.
    pause
    exit /b 1
)

python main.py %*
set EXITCODE=%ERRORLEVEL%
if not %EXITCODE%==0 (
    echo.
    echo Aplikasi keluar dengan kode %EXITCODE%.
    pause
)
endlocal
