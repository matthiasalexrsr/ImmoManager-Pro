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

REM Install all project dependencies + PyInstaller
echo Installiere Abhaengigkeiten...
pip install --upgrade pip setuptools wheel -q
pip install -e ".[build]" -q
if %errorlevel% neq 0 (
    echo FEHLER: pip install fehlgeschlagen.
    pause
    exit /b 1
)
echo [OK] Abhaengigkeiten installiert

REM Build frontend (always rebuild to ensure dist is up-to-date)
if exist "frontend\package.json" (
    where npm >nul 2>&1
    if %errorlevel% equ 0 (
        echo.
        echo Installiere Frontend-Abhaengigkeiten und baue Frontend...
        cd frontend
        call npm install
        call npm run build
        if %errorlevel% neq 0 (
            echo FEHLER: Frontend-Build fehlgeschlagen.
            cd ..
            pause
            exit /b 1
        )
        cd ..
        echo [OK] Frontend gebaut
    ) else (
        if not exist "frontend\dist" (
            echo.
            echo FEHLER: npm nicht gefunden und frontend\dist existiert nicht.
            echo         Installieren Sie Node.js oder bauen Sie das Frontend manuell.
            pause
            exit /b 1
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
