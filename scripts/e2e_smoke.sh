#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILES=(
  -f docker-compose.yml
  -f docker-compose.monitoring.yml
)

cleanup() {
  docker compose "${COMPOSE_FILES[@]}" down -v --remove-orphans || true
}
trap cleanup EXIT

docker compose "${COMPOSE_FILES[@]}" up -d --build

for _ in {1..60}; do
  if curl -fsS http://localhost:8000/health >/dev/null; then
    break
  fi
  sleep 2
done

curl -fsS http://localhost:8000/health | tee /tmp/health.json
curl -fsSI http://localhost:8000/mietvertrag/ >/tmp/wizard_headers.txt
curl -fsS http://localhost:9090/-/ready >/dev/null
curl -fsS http://localhost:3001/api/health >/dev/null

grep -q '"status":"ok"' /tmp/health.json
grep -qi '200 OK' /tmp/wizard_headers.txt

echo "E2E smoke checks passed"
