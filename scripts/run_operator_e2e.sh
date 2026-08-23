#!/usr/bin/env bash

# Run the browser journeys against an isolated, deterministic full-stack deployment.
# No external provider endpoint or credential is used.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="${OPERATOR_E2E_PROJECT_NAME:-customer-service-operator-e2e}"
AUTH_CREDENTIAL="${OPERATOR_E2E_AUTH_CREDENTIAL:-local-e2e-operator-credential}"
COMPOSE=(
  docker compose
  --project-name "${PROJECT_NAME}"
  --file docker-compose.yml
  --file docker-compose.integration.yml
  --file docker-compose.operator-e2e.yml
  --env-file .env.example
)

cleanup() {
  "${COMPOSE[@]}" down --volumes --remove-orphans --timeout 20 >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "${ROOT_DIR}"
export LOCAL_DEMO_AUTH_TOKEN="${AUTH_CREDENTIAL}"
export LOCAL_DEMO_ACTOR_ID="operator-e2e"
export BACKEND_PORT=0
export FRONTEND_PORT=0
export POSTGRES_PORT=0
export QDRANT_HTTP_PORT=0
export QDRANT_GRPC_PORT=0
export JAEGER_UI_PORT=0
export OTEL_GRPC_PORT=0
export OTEL_HTTP_PORT=0

if [[ -z "${PLAYWRIGHT_CHROME_PATH:-}" && -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]]; then
  export PLAYWRIGHT_CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
fi

cleanup
"${COMPOSE[@]}" up --build --detach --wait --wait-timeout 240

FRONTEND_ADDRESS="$("${COMPOSE[@]}" port frontend 8080)"
FRONTEND_HOST_PORT="${FRONTEND_ADDRESS##*:}"
if [[ ! "${FRONTEND_HOST_PORT}" =~ ^[0-9]+$ ]]; then
  echo "Could not resolve the isolated frontend port." >&2
  exit 1
fi

PLAYWRIGHT_BASE_URL="http://127.0.0.1:${FRONTEND_HOST_PORT}" \
E2E_CAPTURE_SCREENSHOTS="${E2E_CAPTURE_SCREENSHOTS:-1}" \
npm --prefix frontend run e2e -- "$@"
