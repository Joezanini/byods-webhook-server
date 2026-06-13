#!/usr/bin/env bash
# Build and push the Docker image via AWS CodeBuild when local Docker is unavailable.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INFRA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
ECR_REPO="byods-webhook-server"
IMAGE_TAG="${IMAGE_TAG:-latest}"
PROJECT_NAME="byods-webhook-server-build"
BUCKET_NAME="byods-webhook-build-${AWS_ACCOUNT_ID}"
REPOSITORY_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"

echo "==> Packaging source..."
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
rsync -a \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude 'infra/.venv' \
  --exclude 'infra/cdk.out' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude '.env' \
  "$ROOT_DIR/" "$STAGING/"
cp "$INFRA_DIR/buildspec.yml" "$STAGING/buildspec.yml"
(
  cd "$STAGING"
  zip -qr /tmp/byods-webhook-source.zip .
)

if ! aws s3api head-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
  echo "==> Creating build bucket ${BUCKET_NAME}..."
  if [[ "$AWS_REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" >/dev/null
  else
    aws s3api create-bucket \
      --bucket "$BUCKET_NAME" \
      --region "$AWS_REGION" \
      --create-bucket-configuration "LocationConstraint=${AWS_REGION}" >/dev/null
  fi
fi

echo "==> Uploading source to s3://${BUCKET_NAME}/source.zip"
aws s3 cp /tmp/byods-webhook-source.zip "s3://${BUCKET_NAME}/source.zip" --region "$AWS_REGION" >/dev/null

ROLE_NAME="byods-webhook-codebuild-role"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "==> Creating CodeBuild IAM role..."
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "codebuild.amazonaws.com"},
        "Action": "sts:AssumeRole"
      }]
    }' >/dev/null
  aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser >/dev/null
  aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/CloudWatchLogsFullAccess >/dev/null
  aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "byods-webhook-codebuild-s3" \
    --policy-document "{
      \"Version\": \"2012-10-17\",
      \"Statement\": [{
        \"Effect\": \"Allow\",
        \"Action\": [\"s3:GetObject\", \"s3:GetObjectVersion\", \"s3:ListBucket\"],
        \"Resource\": [
          \"arn:aws:s3:::${BUCKET_NAME}\",
          \"arn:aws:s3:::${BUCKET_NAME}/*\"
        ]
      }]
    }" >/dev/null
  sleep 10
fi

ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)"

PROJECT_EXISTS="$(aws codebuild batch-get-projects --names "$PROJECT_NAME" --region "$AWS_REGION" \
  --query 'length(projects)' --output text 2>/dev/null || echo 0)"
if [[ "$PROJECT_EXISTS" == "0" ]]; then
  echo "==> Creating CodeBuild project ${PROJECT_NAME}..."
  aws codebuild create-project \
    --name "$PROJECT_NAME" \
    --region "$AWS_REGION" \
    --service-role "$ROLE_ARN" \
    --source "type=S3,location=${BUCKET_NAME}/source.zip,buildspec=buildspec.yml" \
    --artifacts type=NO_ARTIFACTS \
    --environment "type=LINUX_CONTAINER,image=aws/codebuild/amazonlinux-x86_64-standard:5.0,computeType=BUILD_GENERAL1_SMALL,privilegedMode=true,environmentVariables=[{name=AWS_DEFAULT_REGION,value=${AWS_REGION},type=PLAINTEXT},{name=REPOSITORY_URI,value=${REPOSITORY_URI},type=PLAINTEXT},{name=IMAGE_TAG,value=${IMAGE_TAG},type=PLAINTEXT}]" \
    --timeout-in-minutes 30 >/dev/null
else
  aws codebuild update-project \
    --name "$PROJECT_NAME" \
    --region "$AWS_REGION" \
    --source "type=S3,location=${BUCKET_NAME}/source.zip,buildspec=buildspec.yml" \
    --environment "type=LINUX_CONTAINER,image=aws/codebuild/amazonlinux-x86_64-standard:5.0,computeType=BUILD_GENERAL1_SMALL,privilegedMode=true,environmentVariables=[{name=AWS_DEFAULT_REGION,value=${AWS_REGION},type=PLAINTEXT},{name=REPOSITORY_URI,value=${REPOSITORY_URI},type=PLAINTEXT},{name=IMAGE_TAG,value=${IMAGE_TAG},type=PLAINTEXT}]" >/dev/null
fi

echo "==> Starting CodeBuild..."
BUILD_ID="$(aws codebuild start-build \
  --project-name "$PROJECT_NAME" \
  --region "$AWS_REGION" \
  --query 'build.id' --output text)"
echo "Build ID: ${BUILD_ID}"

while true; do
  STATUS="$(aws codebuild batch-get-builds --ids "$BUILD_ID" --region "$AWS_REGION" \
    --query 'builds[0].buildStatus' --output text)"
  PHASE="$(aws codebuild batch-get-builds --ids "$BUILD_ID" --region "$AWS_REGION" \
    --query 'builds[0].currentPhase' --output text)"
  echo "  ${PHASE} -> ${STATUS}"
  case "$STATUS" in
    SUCCEEDED) break ;;
    FAILED|FAULT|STOPPED|TIMED_OUT)
      echo "CodeBuild failed. Logs:" >&2
      aws codebuild batch-get-builds --ids "$BUILD_ID" --region "$AWS_REGION" \
        --query 'builds[0].logs.deepLink' --output text >&2
      exit 1
      ;;
  esac
  sleep 15
done

echo "Pushed ${REPOSITORY_URI}:${IMAGE_TAG}"
