#!/usr/bin/env bash
# Append structured debug logs for CI/CD pipeline diagnosis.
# Writes to the Cursor debug log locally; posts to the ingest endpoint in CodeBuild.
set -euo pipefail

pipeline_debug_log() {
  local hypothesis_id="${1:?hypothesisId required}"
  local location="${2:?location required}"
  local message="${3:?message required}"
  local data="${4:-{}}"
  local run_id="${5:-${CODEBUILD_BUILD_ID:-local}}"
  local timestamp
  timestamp="$(python3 -c 'import time; print(int(time.time()*1000))')"

  local payload
  payload="$(HYPOTHESIS_ID="$hypothesis_id" LOCATION="$location" MESSAGE="$message" DATA="$data" RUN_ID="$run_id" TIMESTAMP="$timestamp" python3 - <<'PY'
import json, os
print(json.dumps({
    "sessionId": "7930bc",
    "hypothesisId": os.environ["HYPOTHESIS_ID"],
    "location": os.environ["LOCATION"],
    "message": os.environ["MESSAGE"],
    "data": json.loads(os.environ["DATA"]),
    "runId": os.environ["RUN_ID"],
    "timestamp": int(os.environ["TIMESTAMP"]),
}))
PY
)"

  local log_path="/Users/joezanini/byods-webhook-server/.cursor/debug-7930bc.log"
  if [[ -w "$(dirname "$log_path")" ]] 2>/dev/null; then
    printf '%s\n' "$payload" >>"$log_path"
  fi

  echo "[pipeline-debug] $payload"

  if [[ -n "${CODEBUILD_BUILD_ID:-}" ]]; then
    curl -sS -X POST \
      -H 'Content-Type: application/json' \
      -H 'X-Debug-Session-Id: 7930bc' \
      -d "$payload" \
      'http://127.0.0.1:7637/ingest/97b26d64-98af-4382-b9f9-208cc60d4431' \
      >/dev/null 2>&1 || true
  fi
}
