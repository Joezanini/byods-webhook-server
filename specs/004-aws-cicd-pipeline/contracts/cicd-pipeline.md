# Contract: CI/CD Pipeline Stages and Build Specifications

**Feature**: `004-aws-cicd-pipeline` | **Version**: 1.0.0 | **Date**: 2026-06-13

This contract defines the **stage topology**, **inputs/outputs**, and **buildspec interfaces** for the AWS CodePipeline/CodeBuild delivery system. Implementation MUST conform to these stage boundaries.

---

## Pipelines

### 1. `byods-webhook-release`

**Trigger**: Git push to `main`  
**Source**: GitHub `Joezanini/byods-webhook-server` via CodeStar connection  
**Artifact bucket**: `{account}-byods-pipeline-artifacts` (CDK-created)

| Order | Stage | CodeBuild project | Input artifact | Output |
|-------|-------|-------------------|----------------|--------|
| 1 | Source | — | — | `SourceOutput` (full repo at commit) |
| 2 | Infra | `byods-webhook-infra` | `SourceOutput` | — (CloudFormation stack update) |
| 3 | Build | `byods-webhook-build` | `SourceOutput` | `BuildOutput` (imagedefinitions optional metadata) |
| 4 | Deploy | `byods-webhook-deploy` | `SourceOutput` | — (ECS service updated) |
| 5 | Verify | `byods-webhook-verify` | `SourceOutput` | — (verification log) |

**Execution mode**: Supersede — new push to `main` cancels in-flight release runs (FR-016).

**Manual re-run variable**: Operators may start the release pipeline with `FORCE_INFRA=true` to run the Infra stage without an `infra/**` commit (FR-008).

### 2. `byods-webhook-pr-validation`

**Trigger**: Pull request opened, updated, or reopened (all branches)  
**Stages**: Source → Test (single CodeBuild project `byods-webhook-test`)

| Order | Stage | CodeBuild project | Gate |
|-------|-------|-------------------|------|
| 1 | Source | — | — |
| 2 | Test | `byods-webhook-test` | Must pass before merge (branch protection recommended) |

**Constraint**: MUST NOT call ECR `PutImage`, ECS `UpdateService`, or CDK deploy.

---

## Environment variables (all CodeBuild projects)

| Variable | Source | Used by |
|----------|--------|---------|
| `AWS_DEFAULT_REGION` | `us-east-1` (plaintext) | All |
| `AWS_ACCOUNT_ID` | CodeBuild env / STS | All |
| `STACK_NAME` | `ByodsWebhookStack` | Infra, Deploy, Verify |
| `ECR_REPO` | `byods-webhook-server` | Build |
| `REPOSITORY_URI` | `{account}.dkr.ecr.{region}.amazonaws.com/byods-webhook-server` | Build |
| `IMAGE_TAG` | `$CODEBUILD_RESOLVED_SOURCE_VERSION` | Build |
| `HEALTH_URL` | Stack output or default `https://hooks.atozbuildingcrm.com/health` | Verify |
| `READY_URL` | Stack output or default `https://hooks.atozbuildingcrm.com/ready` | Verify |
| `WEBHOOK_URL` | Stack output or default `https://hooks.atozbuildingcrm.com/webhooks/webex` | Verify |
| `MEDIA_HOST` | Stack output hostname or `media.atozbuildingcrm.com` | Verify |

---

## Buildspec: `infra/buildspec.yml` (existing — Build stage)

**Path in repo**: `infra/buildspec.yml`  
**Privileged**: true  
**Compute**: `BUILD_GENERAL1_SMALL`

**Phases** (unchanged):

```yaml
pre_build: ECR login
build: docker build -t $REPOSITORY_URI:$IMAGE_TAG .
post_build: docker push $IMAGE_TAG and :latest
```

**Contract requirements**:

- MUST push both `$IMAGE_TAG` (commit SHA) and `latest`
- MUST fail stage on any push error
- MUST NOT echo ECR password or secret values

---

## Buildspec: `infra/buildspec-infra.yml` (new — Infra stage)

**Purpose**: Conditional CDK deploy when `infra/**` changes.

**Pre-check** (required):

```bash
if [ "${FORCE_INFRA:-false}" != "true" ]; then
  if ! git diff-tree --no-commit-id --name-only -r "$CODEBUILD_RESOLVED_SOURCE_VERSION" | grep -q '^infra/'; then
    echo "No infra changes; skipping CDK deploy"
    exit 0
  fi
fi
```

**Deploy** (when changes present):

```bash
cd infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk deploy ByodsWebhookStack --require-approval never -c desiredCount=1
```

**IAM**: `cloudformation:*` on `ByodsWebhookStack`, `iam:PassRole` for CDK bootstrap roles, `sts:AssumeRole` for CDK deploy role.

**Constraint**: MUST NOT run `deploy.sh secrets` or read `.env`.

---

## Buildspec: `infra/buildspec-deploy.yml` (new — Deploy stage)

**Purpose**: ECS rolling restart after image push.

**Required commands**:

```bash
CLUSTER=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='EcsClusterName'].OutputValue" --output text)
SERVICE=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='EcsServiceName'].OutputValue" --output text)
aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --force-new-deployment
aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
```

**Timeout**: 15 minutes (covers `health_check_grace_period=180s`).

**Failure**: Stage fails; previous tasks remain until operator fixes and re-runs.

---

## Buildspec: `infra/buildspec-verify.yml` (new — Verify stage)

**Purpose**: Post-deploy smoke tests (FR-005, FR-006).

| Step | Command pattern | Blocking |
|------|-----------------|----------|
| Health | `curl -fsS "$HEALTH_URL"` | Yes |
| Readiness | `curl -sS -o /dev/null -w '%{http_code}' "$READY_URL"` — log code | No |
| Webhook | `curl -sS -o /dev/null -w '%{http_code}' -X POST "$WEBHOOK_URL" -H 'Content-Type: application/json' -d '{}'` — require response | Yes |
| gRPC | `grpcurl ... ListVirtualAgents` if installed | No |

**Exit code**: 0 only if all blocking checks pass.

**Rollback (FR-015)**: On blocking failure, read `previous_task_definition_arn` from the DeployMeta artifact (`$CODEBUILD_SRC_DIR_DeployMeta/deploy-meta/env`) and run `aws ecs update-service --task-definition` before exiting non-zero.

**Output contract**: Final line MUST be JSON summary:

```json
{"health":"pass","readiness":"503-warn","webhook":"400-pass","grpc":"skipped","overall":"pass"}
```

---

## Buildspec: `infra/buildspec-test.yml` (new — PR Test stage)

**Purpose**: Pre-merge validation (FR-012).

```yaml
phases:
  install:
    commands:
      - pip install -r requirements.txt
      - pip install pytest pytest-asyncio httpx  # or requirements-dev.txt if added
  build:
    commands:
      - pytest tests/unit tests/integration -q --ignore=tests/integration/test_list_virtual_agents.py
      - docker build -t byods-webhook-server:pr-test .
```

**Note**: Skip live gRPC integration tests requiring deployed endpoint; unit tests MUST pass.

**IAM**: No ECR push, no ECS, no CloudFormation.

---

## IAM role contracts

### CodePipeline service role

- `codebuild:StartBuild`, `codebuild:BatchGetBuilds`
- `s3:GetObject`, `s3:PutObject` on artifact bucket
- `codestar-connections:UseConnection` on GitHub connection
- `iam:PassRole` to CodeBuild project roles

### `byods-webhook-build` role

- ECR: `GetAuthorizationToken`, `BatchCheckLayerAvailability`, `PutImage`, `InitiateLayerUpload`, `UploadLayerPart`, `CompleteLayerUpload`
- Logs: `CreateLogStream`, `PutLogEvents`

### `byods-webhook-deploy` role

- ECS: `UpdateService`, `DescribeServices`, `DescribeTasks`
- CloudFormation: `DescribeStacks` on `ByodsWebhookStack`
- Logs: write to deploy project log group

### `byods-webhook-infra` role

- CloudFormation full on `ByodsWebhookStack` and CDK assets
- CDK bootstrap SSM/STS as required by `cdk deploy`

### `byods-webhook-verify` role

- CloudFormation: `DescribeStacks` (read URLs)
- No Secrets Manager access

### `byods-webhook-test` role

- Logs only

---

## CDK stack contract: `ByodsPipelineStack`

**File**: `infra/pipeline_stack.py` (new)  
**Deploy command**: `cdk deploy ByodsPipelineStack` (after app stack exists)

**Required outputs**:

| Output key | Value |
|------------|-------|
| `ReleasePipelineName` | `byods-webhook-release` |
| `PrPipelineName` | `byods-webhook-pr-validation` |
| `GitHubConnectionArn` | Connection ARN |
| `ArtifactBucketName` | S3 bucket name |

**Context keys**:

| Key | Default | Purpose |
|-----|---------|---------|
| `githubOwner` | `Joezanini` | Repo owner |
| `githubRepo` | `byods-webhook-server` | Repo name |
| `githubBranch` | `main` | Release trigger branch |
| `githubConnectionArn` | — | Existing connection ARN (if pre-created) |

---

## Out of scope (explicit)

- Webhook OAuth registration (`register_webhooks.py`) — manual per environment
- `deploy.sh secrets` from CI — operators manage Secrets Manager directly
- gRPC verification as release gate — non-blocking in v1
- Multi-environment (staging) pipelines
- Immutable task definition tags (future enhancement)

---

## Compatibility with existing scripts

| Manual command | Pipeline equivalent |
|----------------|---------------------|
| `deploy.sh image` | Build stage |
| `deploy.sh restart` | Deploy stage |
| `deploy.sh verify` | Verify stage |
| `deploy.sh infra 1` | Infra stage (when `infra/**` changed) |
| `deploy.sh all` | One-time bootstrap only (not automated) |
| `codebuild_push.sh` | Replaced by pipeline Build stage for routine use |
