#!/usr/bin/env bash
# ImmoManager Pro — Build Script (Linux / macOS)
#
# Creates a standalone executable in dist/ImmoManager-Pro/
#
# Usage:
#   chmod +x build.sh
#   ./build.sh
#
set -e

echo "======================================"
echo " ImmoManager Pro — Build"
echo "======================================"
echo ""

# Activate venv if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Check PyInstaller
if ! python -m PyInstaller --version &>/dev/null; then
    echo "PyInstaller wird installiert..."
    pip install "pyinstaller>=6.0.0" -q
fi

PYINSTALLER_VER=$(python -m PyInstaller --version 2>&1)
echo "[OK] PyInstaller $PYINSTALLER_VER"

# Build frontend (always rebuild to ensure dist is up-to-date)
if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    if command -v npm &>/dev/null; then
        echo ""
        echo "Installiere Frontend-Abhängigkeiten und baue Frontend..."
        cd frontend
        npm install
        npm run build
        cd ..
        echo "[OK] Frontend gebaut"
    elif [ ! -d "frontend/dist" ]; then
        echo ""
        echo "FEHLER: npm nicht gefunden und frontend/dist existiert nicht."
        echo "        Installieren Sie Node.js oder bauen Sie das Frontend manuell."
        exit 1
    fi
fi

# Clean previous build
rm -rf build/ dist/

echo ""
echo "Starte PyInstaller Build..."
echo ""
python -m PyInstaller immomanager.spec

echo ""
echo "======================================"
echo " Build abgeschlossen!"
echo "======================================"
echo ""
echo "Ausgabe: dist/ImmoManager-Pro/"
echo ""

# Show output size
if [ -d "dist/ImmoManager-Pro" ]; then
    SIZE=$(du -sh dist/ImmoManager-Pro/ | cut -f1)
    echo "Groesse: $SIZE"
    echo ""
    echo "Starten mit:"
    echo "  ./dist/ImmoManager-Pro/ImmoManager-Pro"
    echo "  ./dist/ImmoManager-Pro/ImmoManager-Pro --seed"
fi
echo ""
