@echo off
REM ImmoManager Pro — Build Script (Windows)
REM
REM Creates a standalone .exe in dist\ImmoManager-Pro\
REM
REM Usage:
REM   Doppelklick auf build.bat
REM   oder: build.bat in der Eingabeaufforderung
REM

echo ======================================
echo  ImmoManager Pro — Build (.exe)
echo ======================================
echo.

REM Activate venv if present
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

REM Check PyInstaller
python -m PyInstaller --version >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller wird installiert...
    pip install "pyinstaller>=6.0.0" -q
)

REM Build frontend if not already built
if exist "frontend\package.json" (
    if not exist "frontend\dist" (
        where npm >nul 2>&1
        if %errorlevel% equ 0 (
            echo.
            echo Baue Frontend...
            cd frontend
            call npm install --silent 2>nul
            call npm run build --silent 2>nul
            cd ..
        )
    )
)

REM Clean previous build
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

echo.
echo Starte PyInstaller Build...
echo.
python -m PyInstaller immomanager.spec
if %errorlevel% neq 0 (
    echo.
    echo FEHLER: Build fehlgeschlagen.
    pause
    exit /b 1
)

echo.
echo ======================================
echo  Build abgeschlossen!
echo ======================================
echo.
echo Ausgabe: dist\ImmoManager-Pro\
echo.
echo Starten mit:
echo   dist\ImmoManager-Pro\ImmoManager-Pro.exe
echo   dist\ImmoManager-Pro\ImmoManager-Pro.exe --seed
echo.
pause
