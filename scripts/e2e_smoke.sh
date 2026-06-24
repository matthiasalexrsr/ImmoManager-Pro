#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILES=(
  -f docker-compose.yml
  -f docker-compose.monitoring.yml
)

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    docker compose "${COMPOSE_FILES[@]}" ps || true
    docker compose "${COMPOSE_FILES[@]}" logs --no-color app || true
  fi
  docker compose "${COMPOSE_FILES[@]}" down -v --remove-orphans || true
}
trap cleanup EXIT

# Build the SPA before building the Docker image. The Dockerfile copies
# frontend/dist, so an empty placeholder would make the backend health check pass
# while SPA routes still fail in the release image.
(cd frontend && npm ci && npm run build)

docker compose "${COMPOSE_FILES[@]}" up -d --build

for _ in {1..60}; do
  if curl -fsS http://localhost:8000/health >/dev/null; then
    break
  fi
  sleep 2
done

curl -fsS http://localhost:8000/health | tee /tmp/health.json
curl -fsSI http://localhost:8000/mietvertrag/ >/tmp/wizard_headers.txt
curl -fsS http://localhost:8000/ >/tmp/spa_root.html
curl -fsS http://localhost:8000/contract-wizard >/tmp/spa_contract_wizard.html
curl -fsS http://localhost:9090/-/ready >/dev/null
curl -fsS http://localhost:3001/api/health >/dev/null

grep -q '"status":"ok"' /tmp/health.json
grep -qi '200 OK' /tmp/wizard_headers.txt
grep -q '<div id="root"' /tmp/spa_root.html
grep -q '<div id="root"' /tmp/spa_contract_wizard.html

echo "E2E smoke checks passed"
