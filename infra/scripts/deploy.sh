#!/usr/bin/env bash
# Build, push, and deploy BYODS webhook server to AWS ECS Fargate.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

AWS_REGION="${AWS_REGION:-${CDK_DEFAULT_REGION:-us-east-1}}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
ECR_REPO="byods-webhook-server"
IMAGE_TAG="${IMAGE_TAG:-latest}"
STACK_NAME="${STACK_NAME:-ByodsWebhookStack}"
SECRET_NAME="byods-webhook-server/webex"

usage() {
  cat <<'EOF'
Usage: infra/scripts/deploy.sh [command]

Commands:
  all          Bootstrap CDK (if needed), deploy stack, build/push image, restart ECS (default)
  infra        Deploy or update CDK stack only
  image        Build Docker image and push to ECR
  restart      Force new ECS deployment (after image push)
  secrets      Upload Webex credentials from repo-root .env to Secrets Manager
  verify       Curl health endpoint and grpcurl ListVirtualAgents

Environment:
  AWS_REGION, AWS_ACCOUNT_ID, IMAGE_TAG, STACK_NAME
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: required command not found: $1" >&2
    exit 1
  fi
}

cdk_cmd() {
  if command -v cdk >/dev/null 2>&1; then
    cdk "$@"
  else
    require_cmd npx
    npx --yes aws-cdk@2.1126.0 "$@"
  fi
}

ecr_login() {
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
}

deploy_infra() {
  require_cmd aws
  require_cmd python3

  cd "$INFRA_DIR"
  if [[ ! -d .venv ]]; then
    python3 -m venv .venv
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -q -r requirements.txt

  export CDK_DEFAULT_ACCOUNT="$AWS_ACCOUNT_ID"
  export CDK_DEFAULT_REGION="$AWS_REGION"

  if ! aws cloudformation describe-stacks --stack-name CDKToolkit --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "==> Bootstrapping CDK in ${AWS_REGION}..."
    cdk_cmd bootstrap "aws://${AWS_ACCOUNT_ID}/${AWS_REGION}"
  fi

  local desired_count="${1:-0}"
  echo "==> Deploying CDK stack ${STACK_NAME} (desiredCount=${desired_count})..."
  cdk_cmd deploy "$STACK_NAME" --require-approval never -c "desiredCount=${desired_count}"
}

build_and_push_image() {
  require_cmd aws

  if ! aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "error: ECR repository ${ECR_REPO} not found. Run: $0 infra" >&2
    exit 1
  fi

  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    local image_uri="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}"
    echo "==> Logging in to ECR..."
    ecr_login
    echo "==> Building image ${image_uri}..."
    docker build -t "$image_uri" "$ROOT_DIR"
    echo "==> Pushing image..."
    docker push "$image_uri"
    echo "Pushed ${image_uri}"
  else
    echo "==> Local Docker unavailable; building via AWS CodeBuild..."
    bash "${INFRA_DIR}/scripts/codebuild_push.sh"
  fi
}

upload_secrets() {
  require_cmd aws
  local env_file="${ROOT_DIR}/.env"
  if [[ ! -f "$env_file" ]]; then
    echo "error: ${env_file} not found" >&2
    exit 1
  fi

  # shellcheck disable=SC1090
  set -a
  source "$env_file"
  set +a

  for key in \
    WEBEX_INTEGRATION_CLIENT_ID \
    WEBEX_INTEGRATION_CLIENT_SECRET \
    WEBEX_SA_CLIENT_ID \
    WEBEX_SA_CLIENT_SECRET \
    WEBEX_INTEGRATION_REFRESH_TOKEN \
    PERSISTENCE_ENCRYPTION_KEY; do
    if [[ -z "${!key:-}" ]]; then
      echo "warning: ${key} is empty in .env" >&2
    fi
  done

  local payload
  payload="$(python3 - <<PY
import json
import os
import subprocess

keys = [
    "WEBEX_INTEGRATION_CLIENT_ID",
    "WEBEX_INTEGRATION_CLIENT_SECRET",
    "WEBEX_SA_CLIENT_ID",
    "WEBEX_SA_CLIENT_SECRET",
    "WEBEX_INTEGRATION_REFRESH_TOKEN",
    "PERSISTENCE_ENCRYPTION_KEY",
]
secret_name = "${SECRET_NAME}"
region = "${AWS_REGION}"
existing = {}
try:
    raw = subprocess.check_output(
        [
            "aws", "secretsmanager", "get-secret-value",
            "--secret-id", secret_name,
            "--region", region,
            "--query", "SecretString",
            "--output", "text",
        ],
        text=True,
    )
    existing = json.loads(raw)
except subprocess.CalledProcessError:
    pass

merged = {}
for key in keys:
    value = os.environ.get(key, "")
    if value:
        merged[key] = value
    elif key in existing:
        merged[key] = existing[key]
    else:
        merged[key] = ""
print(json.dumps(merged))
PY
)"

  if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo "==> Updating secret ${SECRET_NAME}..."
    aws secretsmanager put-secret-value \
      --secret-id "$SECRET_NAME" \
      --secret-string "$payload" \
      --region "$AWS_REGION" >/dev/null
  else
    echo "error: secret ${SECRET_NAME} not found. Deploy infra first." >&2
    exit 1
  fi
  echo "Secret ${SECRET_NAME} updated."
}

restart_service() {
  require_cmd aws
  local cluster service
  cluster="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EcsClusterName'].OutputValue" \
    --output text)"
  service="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='EcsServiceName'].OutputValue" \
    --output text)"

  if [[ -z "$cluster" || -z "$service" || "$cluster" == "None" || "$service" == "None" ]]; then
    echo "error: could not resolve ECS cluster/service from stack outputs" >&2
    exit 1
  fi

  echo "==> Forcing new deployment for ${cluster}/${service}..."
  aws ecs update-service \
    --cluster "$cluster" \
    --service "$service" \
    --force-new-deployment \
    --region "$AWS_REGION" >/dev/null
  echo "Deployment started. Watch: aws ecs wait services-stable --cluster ${cluster} --services ${service} --region ${AWS_REGION}"
}

verify_endpoints() {
  require_cmd curl
  local hooks_url media_host
  hooks_url="$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='HealthUrl'].OutputValue" \
    --output text)"
  media_host="$(python3 - <<'PY'
import json, os, subprocess
region = os.environ.get("AWS_REGION", "us-east-1")
stack = os.environ.get("STACK_NAME", "ByodsWebhookStack")
out = subprocess.check_output([
    "aws", "cloudformation", "describe-stacks",
    "--stack-name", stack,
    "--region", region,
    "--query", "Stacks[0].Outputs[?OutputKey=='MediaGrpcUrl'].OutputValue",
    "--output", "text",
], text=True).strip()
from urllib.parse import urlparse
print(urlparse(out).hostname)
PY
)"

  echo "==> HTTP health: ${hooks_url}"
  curl -fsS "$hooks_url"
  echo

  if command -v grpcurl >/dev/null 2>&1; then
    echo "==> gRPC ListVirtualAgents on ${media_host}:443"
    grpcurl \
      -H 'trackingid: aws-deploy-test' \
      "${media_host}:443" \
      com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents
    echo
  else
    echo "skip: grpcurl not installed (brew install grpcurl)"
  fi
}

print_post_deploy_checklist() {
  cat <<EOF

Post-deploy checklist:
  1. Populate secrets (if not done): infra/scripts/deploy.sh secrets
  2. Register webhooks locally:
       export WEBEX_WEBHOOK_TARGET_URL=https://hooks.atozbuildingcrm.com/webhooks/webex
       python scripts/register_webhooks.py
     Then re-run: infra/scripts/deploy.sh secrets && infra/scripts/deploy.sh restart
  3. Verify: infra/scripts/deploy.sh verify

EOF
}

cmd="${1:-all}"
case "$cmd" in
  all)
    deploy_infra 0
    if [[ -f "${ROOT_DIR}/.env" ]]; then
      upload_secrets
    else
      echo "error: ${ROOT_DIR}/.env required before starting ECS tasks" >&2
      exit 1
    fi
    build_and_push_image
    deploy_infra 1
    print_post_deploy_checklist
    ;;
  infra)
    deploy_infra "${2:-0}"
    ;;
  image)
    build_and_push_image
    ;;
  restart)
    restart_service
    ;;
  secrets)
    upload_secrets
    ;;
  verify)
    verify_endpoints
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "error: unknown command: $cmd" >&2
    usage
    exit 1
    ;;
esac
