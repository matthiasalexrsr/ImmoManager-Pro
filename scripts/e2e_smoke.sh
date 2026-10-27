#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILES=(
  -f docker-compose.yml
  -f docker-compose.monitoring.yml
)

# docker-compose.yml runs the production profile and refuses to start without its
# secrets and boundary settings; the smoke run gets throwaway values that live only as
# long as this run. The checks below talk to the app directly, not through a proxy.
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(openssl rand -hex 24)}"
export JWT_SECRET_KEY="${JWT_SECRET_KEY:-$(openssl rand -hex 32)}"
export BACKUP_PASSPHRASE="${BACKUP_PASSPHRASE:-$(openssl rand -hex 32)}"
export GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-$(openssl rand -hex 16)}"
export CORS_ORIGINS="${CORS_ORIGINS:-https://immomanager.smoke.invalid}"
export TRUSTED_PROXY_IPS="${TRUSTED_PROXY_IPS:-127.0.0.1/32}"

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

# Wait for every service the checks below ask: the app, Prometheus and Grafana start at
# their own pace, and asking one seconds after its start resets the connection.
wait_for() {
  for _ in {1..60}; do
    if curl -fsS "$1" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Not ready after 120 s: $1" >&2
  return 1
}
wait_for http://localhost:8000/health
wait_for http://localhost:9090/-/ready
wait_for http://localhost:3001/api/health

curl -fsS http://localhost:8000/health | tee /tmp/health.json
curl -fsS -o /tmp/wizard.html -w '%{http_code}' http://localhost:8000/mietvertrag/ >/tmp/wizard_status.txt
curl -fsS http://localhost:8000/ >/tmp/spa_root.html
curl -fsS http://localhost:8000/contract-wizard >/tmp/spa_contract_wizard.html
curl -fsS http://localhost:9090/-/ready >/dev/null
curl -fsS http://localhost:3001/api/health >/dev/null

grep -q '"status":"ok"' /tmp/health.json
grep -q '^200$' /tmp/wizard_status.txt
grep -q '<div id="root"' /tmp/spa_root.html
grep -q '<div id="root"' /tmp/spa_contract_wizard.html

# The image really runs the checked production profile: the entrypoint accepted the
# deployment settings, and the API schema is not published (the SPA answers the path).
docker compose "${COMPOSE_FILES[@]}" logs --no-color app >/tmp/app.log
grep -q 'Deployment configuration checked (production)' /tmp/app.log
curl -sS http://localhost:8000/openapi.json >/tmp/openapi.txt || true
if grep -q '"openapi"' /tmp/openapi.txt; then
  echo "The API schema is public in the production profile" >&2
  exit 1
fi

echo "E2E smoke checks passed"
