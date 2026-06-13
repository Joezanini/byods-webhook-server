# AWS deployment guide

This document describes the current AWS deployment for the BYODS webhook server and BYOVA gRPC media endpoint. It is intended for operators and for coding agents that will later wire up CI/CD.

**Status:** Manual deploy via CDK + shell scripts. CI/CD pipeline is not implemented yet.

## Public URLs (production)

Domain: **atozbuildingcrm.com** (Route 53 hosted zone must exist in the target AWS account before first deploy).

| Purpose | URL | Notes |
|---------|-----|-------|
| Webex serviceApp webhooks | `https://hooks.atozbuildingcrm.com/webhooks/webex` | Register this in Webex; set `WEBEX_WEBHOOK_TARGET_URL` |
| HTTP health probe | `https://hooks.atozbuildingcrm.com/health` | ALB + ECS health checks |
| Integration readiness | `https://hooks.atozbuildingcrm.com/ready` | Returns 503 until `WEBEX_INTEGRATION_REFRESH_TOKEN` bootstraps |
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

## Webex webhook registration (one-time per environment)

Run **locally** after the hooks URL is live. OAuth redirect stays on localhost per Webex Integration config.

```bash
# In repo root, with .venv active and .env populated
export WEBEX_WEBHOOK_TARGET_URL=https://hooks.atozbuildingcrm.com/webhooks/webex
python scripts/register_webhooks.py
```

The script:

1. Opens browser for Integration OAuth (`WEBEX_INTEGRATION_REDIRECT_URI=http://127.0.0.1:8765/callback`).
2. Prints `WEBEX_INTEGRATION_REFRESH_TOKEN`.
3. Registers serviceApp webhooks pointing at `WEBEX_WEBHOOK_TARGET_URL`.

After registration:

```bash
# Add refresh token to .env, then sync to AWS
./infra/scripts/deploy.sh secrets
./infra/scripts/deploy.sh restart
```

Verify:

```bash
curl -fsS https://hooks.atozbuildingcrm.com/ready
# {"status":"ok"} when integration token is loaded
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
| `WEBEX_INTEGRATION_REFRESH_TOKEN` | Yes (after webhook registration) | Long-lived Integration token |

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
| `WEBEX_VIRTUAL_AGENTS_CONFIG` | `config/virtual_agents.json` |
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

## CI/CD notes (for future agents)

Not implemented yet. Suggested pipeline stages based on current layout:

| Stage | Action | Script / path |
|-------|--------|----------------|
| Build | Docker build + push to ECR | `infra/scripts/deploy.sh image` or CodeBuild [`codebuild_push.sh`](scripts/codebuild_push.sh) |
| Deploy infra | CDK deploy (usually only on infra changes) | `infra/scripts/deploy.sh infra 1` |
| Release | Force ECS rolling deploy of new image | `infra/scripts/deploy.sh restart` |
| Secrets | Sync from CI secret store → Secrets Manager | `infra/scripts/deploy.sh secrets` (pattern only; CI should inject secrets, not use repo `.env`) |
| Smoke test | HTTP health + optional gRPC | `infra/scripts/deploy.sh verify` |

**Important for pipeline design:**

- First deploy must use two-phase flow (`desiredCount=0` → push image → `desiredCount=1`). Later releases only need `image` + `restart` unless CDK changes.
- Do not commit `.env` or refresh tokens to git.
- Webhook registration (`register_webhooks.py`) is a **one-time manual/OAuth step** per environment; store resulting refresh token in Secrets Manager.
- Stack deletion: `UPDATE_ROLLBACK_COMPLETE` stacks must be deleted before redeploy: `aws cloudformation delete-stack --stack-name ByodsWebhookStack --region us-east-1`.
- Estimated dev cost: ~$30–35/month (single Fargate task, ALB, no NAT gateway).

## File reference

```text
infra/
├── AWS_DEPLOYMENT.md      # This file
├── app.py                 # CDK entrypoint
├── stack.py               # ALB + ECS + Route53 + ACM + ECR + secrets
├── cdk.json               # Domain context defaults
├── requirements.txt       # aws-cdk-lib
├── buildspec.yml          # CodeBuild image build
└── scripts/
    ├── deploy.sh          # Main operator script
    └── codebuild_push.sh  # Remote image build when Docker unavailable
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
