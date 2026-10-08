#!/bin/bash
# ImmoManager Pro — Update Script
# Usage: ./scripts/update.sh   (stop the server first; restart it afterwards)
set -euo pipefail

echo "=== ImmoManager Pro Update ==="
echo ""

# 1. Pull latest code
echo "[1/5] Pulling latest code..."
git pull --ff-only origin main || { echo "ERROR: git pull failed. Resolve conflicts first."; exit 1; }

# 2. Install/update Python dependencies (exact versions, whole tree)
echo "[2/5] Installing Python dependencies..."
pip install -r requirements.txt -c constraints.txt --quiet

# 3. Build frontend (exact versions from package-lock.json)
echo "[3/5] Building frontend..."
cd frontend
npm ci --silent
npm run build
cd ..

# 4. Explicit upgrade: verified full backup first, then the migrations (only when needed)
echo "[4/5] Explicit database upgrade (python -m backend.upgrade)..."
python -m backend.upgrade || { echo "ERROR: upgrade failed; see the message above. The server will refuse to start."; exit 1; }

# 5. Show version
echo "[5/5] Checking version..."
python -c "from backend.config import settings; print(f'  Version: {settings.app_version}')" 2>/dev/null || echo "  Version check skipped."

echo ""
echo "=== Update complete! ==="
echo "Restart the server: uvicorn backend.app:app --host 0.0.0.0 --port 8000"
