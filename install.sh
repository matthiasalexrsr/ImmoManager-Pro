#!/usr/bin/env bash
# ImmoManager Pro — Installation Script (Linux / macOS)
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
#
set -e

echo "======================================"
echo " ImmoManager Pro — Installation"
echo "======================================"
echo ""

# Check Python version
PYTHON=${PYTHON:-python3}
if ! command -v "$PYTHON" &>/dev/null; then
    echo "FEHLER: Python 3 nicht gefunden."
    echo "Bitte installieren Sie Python 3.11+ von https://www.python.org"
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "FEHLER: Python 3.11+ erforderlich, gefunden: $PY_VERSION"
    exit 1
fi
echo "[OK] Python $PY_VERSION gefunden"

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo ""
    echo "Erstelle virtuelle Umgebung (.venv)..."
    "$PYTHON" -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate
echo "[OK] Virtuelle Umgebung aktiviert"

# Install dependencies
echo ""
echo "Installiere Abhängigkeiten..."
pip install --upgrade pip setuptools wheel -q
pip install -e ".[dev]" -q
echo "[OK] Abhängigkeiten installiert"

# Check if frontend needs building
if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    if command -v npm &>/dev/null; then
        echo ""
        echo "Baue Frontend..."
        cd frontend
        npm install --silent 2>/dev/null
        npm run build --silent 2>/dev/null
        cd ..
        echo "[OK] Frontend gebaut"
    else
        echo ""
        echo "HINWEIS: npm nicht gefunden — Frontend wird nicht gebaut."
        echo "         Installieren Sie Node.js für die Frontend-Entwicklung."
    fi
fi

echo ""
echo "======================================"
echo " Installation abgeschlossen!"
echo "======================================"
echo ""
echo "Server starten:"
echo "  source .venv/bin/activate"
echo "  python -m backend"
echo ""
echo "Server mit Demo-Daten starten:"
echo "  python -m backend --seed"
echo ""
echo "Tests ausführen:"
echo "  pytest"
echo ""
