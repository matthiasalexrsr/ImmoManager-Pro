#!/bin/bash
# ImmoManager Pro — Update Script
# Usage: ./scripts/update.sh
set -euo pipefail

echo "=== ImmoManager Pro Update ==="
echo ""

# 1. Pull latest code
echo "[1/5] Pulling latest code..."
git pull --ff-only origin main || { echo "ERROR: git pull failed. Resolve conflicts first."; exit 1; }

# 2. Install/update Python dependencies
echo "[2/5] Installing Python dependencies..."
pip install -r requirements.txt --quiet

# 3. Build frontend
echo "[3/5] Building frontend..."
cd frontend
npm install --silent
npm run build
cd ..

# 4. Run database migrations
echo "[4/5] Running database migrations..."
if [ -f alembic.ini ]; then
    alembic upgrade head
    echo "  Migrations applied."
else
    echo "  No alembic.ini found, skipping migrations."
fi

# 5. Show version
echo "[5/5] Checking version..."
python -c "from backend.config import settings; print(f'  Version: {settings.app_version}')" 2>/dev/null || echo "  Version check skipped."

echo ""
echo "=== Update complete! ==="
echo "Restart the server: uvicorn backend.app:app --host 0.0.0.0 --port 8000"
