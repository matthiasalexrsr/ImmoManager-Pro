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

# Even the development smoke installation establishes its schema explicitly;
# the shared container entrypoint performs no hidden migration on any restart.
docker compose "${COMPOSE_FILES[@]}" build app
docker compose "${COMPOSE_FILES[@]}" up -d --wait db
docker compose "${COMPOSE_FILES[@]}" run --rm --no-deps -T app alembic upgrade head
docker compose "${COMPOSE_FILES[@]}" up -d

for _ in {1..60}; do
  if curl -fsS http://localhost:8000/health >/dev/null; then
    break
  fi
  sleep 2
done

curl -fsS http://localhost:8000/health | tee /tmp/health.json
curl -sS -o /tmp/wizard.html -w '%{http_code}' http://localhost:8000/mietvertrag/ >/tmp/wizard_status.txt
curl -fsS http://localhost:8000/ >/tmp/spa_root.html
curl -fsS http://localhost:8000/contract-wizard >/tmp/spa_contract_wizard.html
curl -fsS http://localhost:9090/-/ready >/dev/null
curl -fsS http://localhost:3001/api/health >/dev/null

grep -q '"status":"ok"' /tmp/health.json
grep -q '^401$' /tmp/wizard_status.txt
grep -q '<div id="root"' /tmp/spa_root.html
grep -q '<div id="root"' /tmp/spa_contract_wizard.html

echo "E2E smoke checks passed"
