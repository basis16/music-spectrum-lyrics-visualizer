@echo off
REM ============================================================
REM  Music Spectrum Lyrics Visualizer  -  Windows setup script
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo  Music Spectrum Lyrics Visualizer - SETUP
echo ============================================================
echo.

REM --- Check Python -------------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python tidak terdeteksi di PATH.
    echo         Install Python 3.10+ dari https://www.python.org/downloads/
    echo         Pastikan centang "Add Python to PATH" saat install.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%a in ('python --version 2^>^&1') do set PYVER=%%a
echo [OK] Python terdeteksi: %PYVER%

REM --- Create / reuse venv -----------------------------------------
if not exist "venv\Scripts\python.exe" (
    echo.
    echo Membuat virtual environment di .\venv ...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Gagal membuat venv.
        pause
        exit /b 1
    )
) else (
    echo [OK] venv sudah ada.
)

REM --- Activate venv -----------------------------------------------
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Gagal mengaktifkan venv.
    pause
    exit /b 1
)
echo [OK] Virtual environment aktif.

REM --- Upgrade pip --------------------------------------------------
echo.
echo Mengupgrade pip ...
python -m pip install --upgrade pip

REM --- Install dependencies ----------------------------------------
echo.
echo Menginstall dependencies dari requirements.txt ...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Gagal install dependencies.
    pause
    exit /b 1
)

REM --- Optional: ask whether to install Whisper --------------------
echo.
set /p INSTALL_WHISPER="Install Whisper untuk lirik otomatis? (y/N): "
if /I "!INSTALL_WHISPER!"=="Y" (
    python -m pip install openai-whisper
)

REM --- FFmpeg check -------------------------------------------------
echo.
echo Memeriksa FFmpeg ...
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [WARN] FFmpeg tidak ditemukan.
    where winget >nul 2>nul
    if errorlevel 1 (
        echo.
        echo winget tidak tersedia. Silakan install FFmpeg manual:
        echo   1. Download dari https://www.gyan.dev/ffmpeg/builds/
        echo   2. Ekstrak ZIP, copy folder bin\ffmpeg.exe ke PATH.
        echo Atau jalankan aplikasi dan klik tombol "Install FFmpeg Online".
    ) else (
        set /p INSTALL_FFMPEG="Install FFmpeg via winget sekarang? (y/N): "
        if /I "!INSTALL_FFMPEG!"=="Y" (
            winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
        )
    )
) else (
    echo [OK] FFmpeg sudah terinstall.
    ffmpeg -version | findstr /B "ffmpeg"
)

echo.
echo ============================================================
echo  Setup selesai. Jalankan run.bat untuk membuka aplikasi.
echo ============================================================
pause
endlocal
