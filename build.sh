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

# Build frontend if not already built
if [ -d "frontend" ] && [ -f "frontend/package.json" ] && [ ! -d "frontend/dist" ]; then
    if command -v npm &>/dev/null; then
        echo ""
        echo "Baue Frontend..."
        cd frontend && npm install --silent && npm run build --silent && cd ..
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
