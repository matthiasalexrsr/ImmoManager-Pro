@echo off
REM ImmoManager Pro — Installation Script (Windows)
REM
REM Usage:
REM   Doppelklick auf install.bat
REM   oder: install.bat in der Eingabeaufforderung
REM

echo ======================================
echo  ImmoManager Pro — Installation
echo ======================================
echo.

REM Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo FEHLER: Python nicht gefunden.
    echo Bitte installieren Sie Python 3.11+ von https://www.python.org
    echo Stellen Sie sicher, dass "Add Python to PATH" aktiviert ist.
    pause
    exit /b 1
)

REM Check Python version
python -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
if %errorlevel% neq 0 (
    echo FEHLER: Python 3.11+ erforderlich.
    python --version
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"') do set PY_VER=%%i
echo [OK] Python %PY_VER% gefunden

REM Create virtual environment if needed
if not exist ".venv" (
    echo.
    echo Erstelle virtuelle Umgebung (.venv)...
    python -m venv .venv
)

REM Activate virtual environment
call .venv\Scripts\activate.bat
echo [OK] Virtuelle Umgebung aktiviert

REM Install dependencies
echo.
echo Installiere Abhaengigkeiten...
pip install --upgrade pip setuptools wheel -q
pip install -e ".[dev]" -q
if %errorlevel% neq 0 (
    echo FEHLER: Installation fehlgeschlagen.
    pause
    exit /b 1
)
echo [OK] Abhaengigkeiten installiert

REM Check for frontend
if exist "frontend\package.json" (
    where npm >nul 2>&1
    if %errorlevel% equ 0 (
        echo.
        echo Baue Frontend...
        cd frontend
        call npm install --silent 2>nul
        call npm run build --silent 2>nul
        cd ..
        echo [OK] Frontend gebaut
    ) else (
        echo.
        echo HINWEIS: npm nicht gefunden — Frontend wird nicht gebaut.
    )
)

echo.
echo ======================================
echo  Installation abgeschlossen!
echo ======================================
echo.
echo Server starten:
echo   .venv\Scripts\activate
echo   python -m backend
echo.
echo Server mit Demo-Daten starten:
echo   python -m backend --seed
echo.
echo Tests ausfuehren:
echo   pytest
echo.
echo .exe erstellen:
echo   build.bat
echo.
pause
