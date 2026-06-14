# AWS deployment guide

This document describes the current AWS deployment for the BYODS webhook server and BYOVA gRPC media endpoint. It is intended for operators and for coding agents that will later wire up CI/CD.

**Status:** Manual deploy via CDK + shell scripts. **CI/CD pipelines** implemented in `ByodsPipelineStack` (see [CI/CD pipelines](#cicd-pipelines-codepipeline--codebuild) section).

## Public URLs (production)

Domain: **atozbuildingcrm.com** (Route 53 hosted zone must exist in the target AWS account before first deploy).

| Purpose | URL | Notes |
|---------|-----|-------|
| Webex serviceApp webhooks | `https://hooks.atozbuildingcrm.com/webhooks/webex` | Register this in Webex; set `WEBEX_WEBHOOK_TARGET_URL` |
| HTTP health probe | `https://hooks.atozbuildingcrm.com/health` | ALB + ECS health checks |
| Integration readiness | `https://hooks.atozbuildingcrm.com/ready` | Returns 503 until integration tokens are bootstrapped (DynamoDB or env refresh token) |
| BYOVA gRPC media (WxCC / Flow Designer) | `https://media.atozbuildingcrm.com` | TLS on port **443**, HTTP/2, gRPC |
| BYODS data source URL | `https://media.atozbuildingcrm.com/grpc` | **Use this** when creating/updating data sources |

### How the data source URL is derived

The application builds the BYODS ingestion URL in [`src/config/settings.py`](../src/config/settings.py):

```text
{WEBEX_DATASOURCE_PUBLIC_URL or origin(WEBEX_WEBHOOK_TARGET_URL)}{WEBEX_DATASOURCE_PATH_SUFFIX}
```

In AWS, the ECS task sets:

- `WEBEX_WEBHOOK_TARGET_URL=https://hooks.atozbuildingcrm.com/webhooks/webex`
- `WEBEX_DATASOURCE_PUBLIC_URL=https://media.atozbuildingcrm.com`
- `WEBEX_DATASOURCE_PATH_SUFFIX=/grpc` (default)

So auto-registration and manual CLI commands should use:

```text
https://media.atozbuildingcrm.com/grpc
```

Do **not** use port `50051` in the public URL. The ALB terminates TLS on 443 and forwards gRPC to container port 50051 inside the task.

## Architecture

```text
Route 53
  hooks.atozbuildingcrm.com  ──┐
  media.atozbuildingcrm.com  ────┼──► ALB (HTTPS :443, ACM cert)
                                 │
                    host=hooks.* ──► HTTP target group :8000 ──► FastAPI (uvicorn)
                    host=media.* ──► gRPC target group :50051 ──► BYOVAMediaServer (plaintext in task)

ECS Fargate (1 task, public subnets, assignPublicIp=true)
  └── Container: byods-webhook-server:latest from ECR
```

**TLS:** Terminated at the ALB. Do not set `WEBEX_MEDIA_TLS_CERT` / `WEBEX_MEDIA_TLS_KEY` in ECS.

**IaC:** AWS CDK (Python) in [`infra/`](.), stack name `ByodsWebhookStack`, region default `us-east-1`.

### AWS resources created

| Resource | Name / detail |
|----------|----------------|
| ECR repository | `byods-webhook-server` |
| ECS cluster / service | From CloudFormation outputs `EcsClusterName`, `EcsServiceName` |
| ALB | Internet-facing, HTTPS listener on 443 |
| Secrets Manager | `byods-webhook-server/webex` (JSON key/value) |
| DynamoDB | `byods-app-state` (org credentials, catalog, audit; on-demand billing) |
| CloudWatch Logs | `/ecs/byods-webhook-server` (7-day retention) |
| ACM certificate | `atozbuildingcrm.com` + `*.atozbuildingcrm.com` (DNS validation) |

## Prerequisites

1. AWS account with credentials configured (`aws sts get-caller-identity`).
2. Route 53 hosted zone for `atozbuildingcrm.com` in the deploy region.
3. Local tools: AWS CLI v2, Python 3.11+, Node.js (for `npx aws-cdk`), optional Docker.
4. Webex Developer account: Integration + Service App (see [README](../README.md)).
5. Repo-root [`.env`](../.env) with Webex credentials (never commit).

## First-time deployment

Deploy is **two-phase** so ECS does not start before an image exists in ECR.

```bash
# From repo root
AWS_REGION=us-east-1 ./infra/scripts/deploy.sh all
```

What `all` does:

1. `deploy_infra 0` — CDK deploy with `desiredCount=0` (creates ECR, ALB, DNS, secrets placeholder, ECS service with no running tasks).
2. `secrets` — Upload Webex credentials from `.env` to Secrets Manager.
3. `image` — Build and push Docker image to ECR (`:latest`).
4. `deploy_infra 1` — CDK deploy with `desiredCount=1` (starts the task).

### Deploy script commands

```bash
./infra/scripts/deploy.sh all       # Full first-time or refresh (see above)
./infra/scripts/deploy.sh infra 0   # Stack only, no running tasks
./infra/scripts/deploy.sh infra 1   # Stack only, scale to 1 task
./infra/scripts/deploy.sh image     # Build/push image only
./infra/scripts/deploy.sh secrets   # Sync .env → Secrets Manager
./infra/scripts/deploy.sh restart   # Force new ECS deployment
./infra/scripts/deploy.sh verify    # curl /health (+ grpcurl if installed)
```

### Image build without local Docker

If Docker is not available locally, `deploy.sh image` falls back to [`infra/scripts/codebuild_push.sh`](scripts/codebuild_push.sh), which packages the repo, uploads to S3, and builds via AWS CodeBuild.

### CDK context (optional overrides)

Edit [`infra/cdk.json`](cdk.json) or pass `-c` flags:

| Context key | Default | Meaning |
|-------------|---------|---------|
| `domain` | `atozbuildingcrm.com` | Route 53 zone / cert |
| `hooksSubdomain` | `hooks` | Webhook hostname |
| `mediaSubdomain` | `media` | gRPC hostname |
| `desiredCount` | `0` in cdk.json; scripts pass `0` or `1` | ECS task count |

Example:

```bash
cd infra && npx --yes aws-cdk@2.1126.0 deploy ByodsWebhookStack -c desiredCount=1
```

CDK CLI version must be **≥ 2.1126.0** (schema compatibility with `aws-cdk-lib`).

## Webex Integration OAuth and webhook registration

### Production OAuth callback (recommended)

Register a **second** redirect URI on your Webex Integration matching the deployed callback path:

```text
https://hooks.atozbuildingcrm.com/oauth/webex/callback
```

Set in Secrets Manager / task env:

```text
WEBEX_INTEGRATION_REDIRECT_URI=https://hooks.atozbuildingcrm.com/oauth/webex/callback
```

ALB routes HTTPS to the FastAPI service on the same host; the callback path must reach port 8000. After deploy:

1. Run `python scripts/register_webhooks.py` locally (with production redirect URI in `.env`) to print the authorize URL, **or** start OAuth from the Webex developer portal.
2. Complete consent in a browser; tokens persist to DynamoDB (`INTEGRATION/CREDS`).
3. Server startup and callback success run idempotent webhook ensure via SDK `aensure_service_app_webhooks`.
4. Remove `WEBEX_INTEGRATION_REFRESH_TOKEN` from secrets once DynamoDB holds tokens (storage takes precedence).

Verify:

```bash
curl -fsS https://hooks.atozbuildingcrm.com/ready
# {"status":"ok"} when integration tokens are loaded
```

### Local script fallback (one-time bootstrap)

For initial bootstrap or localhost redirect URI (`http://127.0.0.1:8765/callback`):

```bash
# In repo root, with .venv active and .env populated
export WEBEX_WEBHOOK_TARGET_URL=https://hooks.atozbuildingcrm.com/webhooks/webex
python scripts/register_webhooks.py
```

The script opens a browser (localhost redirect), optionally prints `WEBEX_INTEGRATION_REFRESH_TOKEN`, and registers serviceApp webhooks.

After registration with env-only tokens:

```bash
./infra/scripts/deploy.sh secrets
./infra/scripts/deploy.sh restart
```

## BYODS data source registration

### Automatic (recommended)

When `WEBEX_AUTO_REGISTER_DATASOURCE=true` (default in AWS task env), the server registers a data source on each `authorized` serviceApp webhook. The registered URL is:

```text
https://media.atozbuildingcrm.com/grpc
```

### Manual (CLI)

After a customer admin authorizes the Service App in Control Hub:

```bash
export ORG_ID="<authorized-org-uuid>"

python scripts/manage_datasources.py list --org-id "$ORG_ID"
python scripts/manage_datasources.py create \
  --org-id "$ORG_ID" \
  --url "https://media.atozbuildingcrm.com/grpc"
python scripts/manage_datasources.py get --org-id "$ORG_ID" --id "<data-source-id>"
python scripts/manage_datasources.py update \
  --org-id "$ORG_ID" --id "<id>" --token-lifetime-minutes 720
python scripts/manage_datasources.py delete --org-id "$ORG_ID" --id "<id>"
```

List virtual agents against the deployed endpoint (requires org with registered data source + refresh token in `.env`):

```bash
python scripts/list_virtual_agents.py \
  --target https://media.atozbuildingcrm.com/grpc \
  --org-id "$ORG_ID"
```

## Secrets and environment variables

### Secrets Manager (`byods-webhook-server/webex`)

JSON object synced from `.env` by `deploy.sh secrets`:

| Key | Required | Description |
|-----|----------|-------------|
| `WEBEX_INTEGRATION_CLIENT_ID` | Yes | Integration OAuth |
| `WEBEX_INTEGRATION_CLIENT_SECRET` | Yes | Integration OAuth |
| `WEBEX_SA_CLIENT_ID` | Yes | Service App |
| `WEBEX_SA_CLIENT_SECRET` | Yes | Service App |
| `WEBEX_INTEGRATION_REFRESH_TOKEN` | Optional bootstrap | Used only when DynamoDB has no `INTEGRATION/CREDS`; remove after production OAuth |
| `WEBEX_INTEGRATION_REDIRECT_URI` | Yes | Must match Webex portal; HTTPS path mounts callback on server |
| `PERSISTENCE_ENCRYPTION_KEY` | Yes (production persistence) | Fernet key for org token encryption at rest |

Generate the encryption key locally:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add the value to `.env` as `PERSISTENCE_ENCRYPTION_KEY=...` before running `./infra/scripts/deploy.sh secrets`.

**Migration note:** Existing authorized orgs in memory before this deploy do not auto-migrate. After enabling DynamoDB persistence, customer orgs must re-authorize in Control Hub (or replay authorization webhooks) once.

### Plain ECS environment (set in CDK)

| Variable | AWS value |
|----------|-----------|
| `WEBEX_WEBHOOK_TARGET_URL` | `https://hooks.atozbuildingcrm.com/webhooks/webex` |
| `WEBEX_DATASOURCE_PUBLIC_URL` | `https://media.atozbuildingcrm.com` |
| `WEBEX_AUTO_REGISTER_DATASOURCE` | `true` |
| `WEBEX_MEDIA_ENABLED` | `true` |
| `WEBEX_MEDIA_HOST` | `0.0.0.0` |
| `WEBEX_MEDIA_PORT` | `50051` |
| `WEBEX_MEDIA_VERIFY_TOKENS` | `true` |
| `WEBEX_VIRTUAL_AGENTS_CONFIG` | `config/virtual_agents.json` (bootstrap seed only) |
| `PERSISTENCE_BACKEND` | `dynamodb` |
| `DYNAMODB_TABLE_NAME` | `byods-app-state` (CloudFormation output `AppStateTableName`) |
| `PORT` | `8000` |
| `LOG_JSON` | `true` |

## Verification

```bash
# HTTP
curl -fsS https://hooks.atozbuildingcrm.com/health
curl -fsS https://hooks.atozbuildingcrm.com/ready

# Webhook route reachable (400 expected for invalid body)
curl -sS -o /dev/null -w "%{http_code}\n" \
  -X POST https://hooks.atozbuildingcrm.com/webhooks/webex \
  -H 'Content-Type: application/json' -d '{}'

# gRPC (requires grpcurl + proto/reflection; server may require JWS when verify_tokens=true)
grpcurl -max-time 15 \
  -H 'trackingid: smoke-test' \
  -d '{}' \
  media.atozbuildingcrm.com:443 \
  com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents

# Or use the project script with a datasource JWS token
./infra/scripts/deploy.sh verify
```

### CloudFormation outputs

After deploy:

```bash
aws cloudformation describe-stacks --stack-name ByodsWebhookStack --region us-east-1 \
  --query 'Stacks[0].Outputs' --output table
```

Key outputs: `HooksUrl`, `MediaGrpcUrl`, `HealthUrl`, `EcrRepositoryUri`, `WebexSecretArn`, `EcsClusterName`, `EcsServiceName`.

### Target group health

```bash
# HTTP target should be healthy on port 8000
# gRPC target should be healthy on port 50051 (see known issue below)
aws elbv2 describe-target-health --target-group-arn <arn> --region us-east-1
```

Logs:

```bash
aws logs tail /ecs/byods-webhook-server --region us-east-1 --follow
```

## Known operational issue: gRPC ALB health checks

With `WEBEX_MEDIA_VERIFY_TOKENS=true`, the ALB gRPC health check calls `ListVirtualAgents` **without** a JWS `authorization` metadata header. The server rejects those requests, so the **gRPC target group may show unhealthy** even when the process is running.

Symptoms:

- HTTP `/health` and webhooks work.
- gRPC target group: `unhealthy`, CloudWatch shows `Missing authorization token` on `ListVirtualAgents`.

Mitigations (choose one before production hardening):

1. **App change:** Skip token verification for `ListVirtualAgents` only (keep verification on `ProcessCallerInput`).
2. **Env change (dev only):** Set `WEBEX_MEDIA_VERIFY_TOKENS=false` in the ECS task definition.
3. **Infra change:** Adjust ALB gRPC health check matcher if a non-zero gRPC status is returned for unauthenticated discovery calls.

Track this when implementing CI/CD smoke tests against `media.atozbuildingcrm.com`.

## CI/CD pipelines (CodePipeline + CodeBuild)

**Status:** Implemented in `infra/pipeline_stack.py` (`ByodsPipelineStack`). Deploy after `ByodsWebhookStack` exists.

### Pipelines

| Pipeline | Trigger | Stages |
|----------|---------|--------|
| `byods-webhook-release` | Push to `main` | Source → Infra* → Build → Deploy → Verify |
| `byods-webhook-pr-validation` | PR opened/updated | Source → Test |

\* Infra skips when no `infra/**` changes unless manual re-run sets `FORCE_INFRA=true`.

**Concurrency (FR-016):** Release pipeline uses supersede mode — a new push cancels an in-flight run.

### First-time pipeline setup

1. Ensure `ByodsWebhookStack` is deployed (`./infra/scripts/deploy.sh all` if greenfield).
2. Create/authorize GitHub CodeStar connection in AWS Console (Developer Tools → Connections), or pass existing ARN:

   ```bash
   cd infra
   source .venv/bin/activate
   export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
   export CDK_DEFAULT_REGION=us-east-1
   cdk deploy ByodsPipelineStack \
     -c githubConnectionArn=arn:aws:codestar-connections:us-east-1:ACCOUNT:connection/UUID
   ```

3. If CDK creates a new connection, open AWS Console → Connections → **Update pending connection** → authorize GitHub org `Joezanini` / repo `byods-webhook-server`.

   Current connection (pending until authorized):

   ```text
   arn:aws:codestar-connections:us-east-1:782781396561:connection/f55f72d1-76a0-4e3d-a66f-408a1aeac76d
   ```

4. (Recommended) Enable GitHub branch protection on `main` requiring the PR pipeline check `byods-webhook-pr-validation` (see GitHub → Settings → Branches).

### Routine release (application change)

Merge to `main` → release pipeline:

1. **Infra** — skipped if commit has no `infra/**` changes
2. **Build** — `infra/buildspec.yml` → ECR push (`:latest` + commit SHA)
3. **Deploy** — `infra/buildspec-deploy.yml` → ECS force-new-deployment
4. **Verify** — `infra/buildspec-verify.yml` → HTTP health + webhook checks; **auto-rollback** on blocking failure (FR-015)

Manual fallback: `./infra/scripts/deploy.sh image && ./infra/scripts/deploy.sh restart`

### Force infrastructure deploy

Re-run `byods-webhook-release` from CodePipeline Console → **Release change** → set variable `FORCE_INFRA=true` (FR-008).

### Pull-request validation

Opening/updating a PR runs `byods-webhook-pr-validation`: `pytest` + `docker build` only (no ECR push, no ECS deploy).

### Secrets policy

- Pipeline IAM roles **deny** `secretsmanager:GetSecretValue` on `byods-webhook-server/webex`.
- Webex credentials remain in Secrets Manager; ECS task loads them at runtime.
- **Do not** use `deploy.sh secrets` from CI or commit `.env`.
- Webhook OAuth (`register_webhooks.py`) stays a **one-time manual** step per environment.

### Buildspec reference

| File | Stage |
|------|-------|
| `infra/buildspec.yml` | Build (image push) |
| `infra/buildspec-infra.yml` | Infra (conditional CDK) |
| `infra/buildspec-deploy.yml` | Deploy (ECS rollout) |
| `infra/buildspec-verify.yml` | Verify (smoke + rollback) |
| `infra/buildspec-test.yml` | PR Test |

### Troubleshooting

| Issue | Action |
|-------|--------|
| Pipeline never triggers | Confirm CodeStar connection status is **Available** |
| Infra stage failed, stack `UPDATE_ROLLBACK_COMPLETE` | `aws cloudformation delete-stack --stack-name ByodsWebhookStack --region us-east-1`, fix CDK, redeploy |
| Verify fails but HTTP works | Check blocking vs non-blocking checks; gRPC is non-blocking in v1 |
| Deploy fails mid-rollout | Production stays on last stable deployment (FR-017); fix and re-run pipeline |

See `specs/004-aws-cicd-pipeline/quickstart.md` for validation scenarios.

### Legacy manual stages (reference)

| Stage | Manual equivalent |
|-------|-------------------|
| Build | `infra/scripts/deploy.sh image` |
| Deploy | `infra/scripts/deploy.sh restart` |
| Infra | `infra/scripts/deploy.sh infra 1` |
| Verify | `infra/scripts/deploy.sh verify` |
| Bootstrap | `infra/scripts/deploy.sh all` (one-time) |

**Important:**

- First environment bootstrap still uses two-phase flow via `deploy.sh all`.
- Do not commit `.env` or refresh tokens to git.
- Estimated pipeline overhead ~$1–5/month atop ~$30–35/month ECS/ALB footprint.

## File reference

```text
infra/
├── AWS_DEPLOYMENT.md      # This file
├── app.py                 # CDK entrypoint (ByodsWebhookStack + ByodsPipelineStack)
├── stack.py               # ALB + ECS + Route53 + ACM + ECR + secrets
├── pipeline_stack.py      # CodePipeline + CodeBuild CI/CD
├── cdk.json               # Domain + GitHub context defaults
├── requirements.txt       # aws-cdk-lib
├── buildspec.yml          # Release: image build
├── buildspec-infra.yml    # Release: conditional CDK deploy
├── buildspec-deploy.yml   # Release: ECS rollout
├── buildspec-verify.yml   # Release: smoke tests + rollback
├── buildspec-test.yml     # PR: pytest + docker build
└── scripts/
    ├── deploy.sh          # Manual operator script (fallback)
    ├── codebuild_push.sh  # Legacy remote build (superseded by pipeline)
    └── pipeline_common.sh # Shared CodeBuild helpers
```

## Quick reference card

```text
Webhook URL:     https://hooks.atozbuildingcrm.com/webhooks/webex
Data source URL: https://media.atozbuildingcrm.com/grpc
Health:          https://hooks.atozbuildingcrm.com/health
Ready:           https://hooks.atozbuildingcrm.com/ready
ECR:             <account>.dkr.ecr.us-east-1.amazonaws.com/byods-webhook-server:latest
Secret:          byods-webhook-server/webex
Logs:            /ecs/byods-webhook-server
```
