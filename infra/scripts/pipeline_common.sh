#!/usr/bin/env bash
# Shared helpers for CodeBuild pipeline stages (deploy, verify, infra).
set -euo pipefail

: "${AWS_DEFAULT_REGION:=${AWS_REGION:-us-east-1}}"
: "${STACK_NAME:=ByodsWebhookStack}"

resolve_stack_output() {
  local key="$1"
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_DEFAULT_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='${key}'].OutputValue" \
    --output text
}

resolve_cluster_service() {
  ECS_CLUSTER="$(resolve_stack_output EcsClusterName)"
  ECS_SERVICE="$(resolve_stack_output EcsServiceName)"
  if [[ -z "$ECS_CLUSTER" || -z "$ECS_SERVICE" || "$ECS_CLUSTER" == "None" || "$ECS_SERVICE" == "None" ]]; then
    echo "error: could not resolve ECS cluster/service from stack ${STACK_NAME}" >&2
    exit 1
  fi
  export ECS_CLUSTER ECS_SERVICE
}

resolve_health_urls() {
  local health_url ready_url hooks_url media_url
  health_url="$(resolve_stack_output HealthUrl)"
  hooks_url="$(resolve_stack_output HooksUrl)"
  media_url="$(resolve_stack_output MediaGrpcUrl)"

  export HEALTH_URL="${HEALTH_URL:-$health_url}"
  export READY_URL="${READY_URL:-${health_url%/health}/ready}"
  export WEBHOOK_URL="${WEBHOOK_URL:-$hooks_url}"
  if [[ -n "$media_url" && "$media_url" != "None" ]]; then
    export MEDIA_HOST="${MEDIA_HOST:-$(python3 - <<PY
from urllib.parse import urlparse
print(urlparse("${media_url}").hostname or "")
PY
)}"
  fi
  export MEDIA_HOST="${MEDIA_HOST:-media.atozbuildingcrm.com}"
}
