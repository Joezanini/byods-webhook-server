#!/usr/bin/env bash
# Append structured debug logs for CI/CD pipeline diagnosis.
# Writes to the Cursor debug log locally; posts to the ingest endpoint in CodeBuild.
set -euo pipefail

pipeline_debug_log() {
  local hypothesis_id="${1:?hypothesisId required}"
  local location="${2:?location required}"
  local message="${3:?message required}"
  shift 3

  local payload
  payload="$(PDL_HYPOTHESIS_ID="$hypothesis_id" \
    PDL_LOCATION="$location" \
    PDL_MESSAGE="$message" \
    PDL_RUN_ID="${CODEBUILD_BUILD_ID:-local}" \
    python3 - "$@" <<'PY'
import json
import os
import sys
import time


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


data = {}
for arg in sys.argv[1:]:
    key, sep, value = arg.partition("=")
    if sep:
        data[key] = parse_value(value)

print(
    json.dumps(
        {
            "sessionId": "7930bc",
            "hypothesisId": os.environ["PDL_HYPOTHESIS_ID"],
            "location": os.environ["PDL_LOCATION"],
            "message": os.environ["PDL_MESSAGE"],
            "data": data,
            "runId": os.environ["PDL_RUN_ID"],
            "timestamp": int(time.time() * 1000),
        }
    )
)
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
