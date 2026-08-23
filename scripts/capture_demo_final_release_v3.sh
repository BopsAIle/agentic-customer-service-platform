#!/usr/bin/env bash

# Capture the final public showcase package from local deterministic projections.
# No provider request, confirmation, or mutation is issued.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${DEMO_UI_URL:-http://localhost:5173}"
CHROME_BIN="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
OUTPUT_DIR="${DEMO_RELEASE_V3_SCREENSHOT_DIR:-${ROOT_DIR}/screenshots/demo-final-release-v3}"
REFUND_RUN_ID="${DEMO_REFUND_RUN_ID:-demo-refund-memory-rag-20260823}"

if [[ ! -x "${CHROME_BIN}" ]]; then
  echo "Chrome executable not found: ${CHROME_BIN}" >&2
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

capture() {
  local name="$1"
  local viewport="$2"
  local path="$3"
  local url="$4"
  "${CHROME_BIN}" \
    --headless=new \
    --disable-gpu \
    --disable-extensions \
    --no-sandbox \
    --hide-scrollbars \
    --run-all-compositor-stages-before-draw \
    --virtual-time-budget=7000 \
    --window-size="${viewport}" \
    --screenshot="${OUTPUT_DIR}/${path}" \
    "${BASE_URL}${url}" >/dev/null 2>&1
  echo "captured ${name}: ${OUTPUT_DIR}/${path}"
}

capture "control-plane overview" "1440,900" "01-control-plane-overview.png" "/showcase"
capture "refund confirmation boundary" "1440,900" "02-refund-confirmation-boundary.png" "/showcase?scenario=refund-memory-rag&compact=1&focus=confirmation"
capture "prompt injection policy prevention" "1440,900" "03-prompt-injection-policy-deny.png" "/showcase?scenario=prompt-injection-defense&compact=1"
capture "idempotency protection" "1440,900" "04-idempotency-protection.png" "/showcase?scenario=duplicate-operation-protection&compact=1"
capture "missing information clarification" "1440,900" "05-missing-information-clarification.png" "/showcase?scenario=missing-information-clarification&compact=1"
capture "operational run registry" "1440,900" "06-operational-run-registry.png" "/traces?fixtures=1"
capture "authority flow" "1440,900" "07-authority-flow.png" "/runs/${REFUND_RUN_ID}?focus=evidence"
capture "investigation report" "1440,900" "08-investigation-report.png" "/runs/${REFUND_RUN_ID}?report=1"
capture "mobile investigation" "390,844" "09-mobile-view.png" "/runs/${REFUND_RUN_ID}"

echo "Final control-plane v3 screenshot capture complete."
