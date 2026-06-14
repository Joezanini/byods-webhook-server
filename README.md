# BYODS Webhook Server

[FastAPI](https://fastapi.tiangolo.com/) service for Webex Contact Center **serviceApp** lifecycle webhooks and **BYOVA** gRPC media, powered entirely by the [webex-byova](https://pypi.org/project/webex-byova/) SDK (`>=0.2.0` with `[media]` extra).

## What it does

- `POST /webhooks/webex` — serviceApp `authorized` / `deauthorized` webhooks via SDK
- `GET {WEBEX_INTEGRATION_REDIRECT_URI path}` — Integration OAuth callback (production HTTPS redirect only; localhost uses `register_webhooks.py`)
- `GET /health` / `GET /ready` — deployment probes
- **gRPC media** on `WEBEX_MEDIA_PORT` (default `50051`) via SDK `BYOVAMediaServer`
- **Virtual agent catalog** for Flow Designer via gRPC `ListVirtualAgents` (DynamoDB-backed when `PERSISTENCE_BACKEND=dynamodb`)
- **BYODS CRUD** via CLI script (`scripts/manage_datasources.py`) — no REST API

On **authorized**, the SDK stores org-scoped Service App tokens in **DynamoDB** (encrypted) when persistence is enabled. When `WEBEX_AUTO_REGISTER_DATASOURCE=true`, a BYODS data source is registered automatically. On **deauthorized**, tokens are removed.

## Prerequisites

1. [Webex Developer](https://developer.webex.com/) account
2. **Webex Integration** with scopes: `spark:all`, `spark:applications_token`, `application:webhooks_write`, `application:webhooks_read`
3. **Webex Service App** with BYODS scopes (`spark-admin:datasource_read`, `spark-admin:datasource_write`)
4. Redirect URI on Integration: `http://127.0.0.1:8765/callback` for local script, or production HTTPS path (e.g. `https://your-host/oauth/webex/callback`) registered in the Webex developer portal

## Integration OAuth (production callback)

When `WEBEX_INTEGRATION_REDIRECT_URI` points at a **non-localhost** HTTPS URL, the server mounts a callback route at that path. Complete OAuth externally (developer portal or printed authorize URL from `register_webhooks.py`); tokens are stored in DynamoDB (`INTEGRATION/CREDS`).

**Precedence**: Durable storage wins over `WEBEX_INTEGRATION_REFRESH_TOKEN` once tokens are persisted. Remove the env refresh token after successful OAuth to avoid confusion.

```bash
# Production .env excerpt
WEBEX_INTEGRATION_REDIRECT_URI=https://your-host.example.com/oauth/webex/callback
WEBEX_WEBHOOK_TARGET_URL=https://your-host.example.com/webhooks/webex
PERSISTENCE_BACKEND=dynamodb
PERSISTENCE_ENCRYPTION_KEY=<fernet-key>
# WEBEX_INTEGRATION_REFRESH_TOKEN=   # optional bootstrap only when storage empty
```

See `specs/006-webex-oauth-callback/quickstart.md` for validation steps.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/ensure_sdk_media_protos.py  # once, if SDK media stubs are missing
cp .env.example .env
# Edit .env with your Webex credentials
```

## Run the server

```bash
# Optional bootstrap when DynamoDB has no integration tokens yet:
# export WEBEX_INTEGRATION_REFRESH_TOKEN=...
uvicorn main:app --host 0.0.0.0 --port 8000
```

With media enabled (default), gRPC listens on `WEBEX_MEDIA_PORT` (50051). Verify:

```bash
grpcurl -plaintext localhost:50051 list
```

## Persistent application state (DynamoDB)

Org authorization credentials and the virtual agent catalog survive restarts and multi-instance deployments when `PERSISTENCE_BACKEND=dynamodb` (default in `.env.example`).

```bash
# Generate a Fernet encryption key for org token blobs at rest
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Add to .env:
# PERSISTENCE_ENCRYPTION_KEY=<generated-key>
# DYNAMODB_TABLE_NAME=byods-app-state
# AWS_ENDPOINT_URL=http://localhost:8001   # DynamoDB Local only
```

**Local DynamoDB** (optional, via Docker Compose):

```bash
docker compose up -d dynamodb-local
aws dynamodb create-table --endpoint-url http://localhost:8001 \
  --table-name byods-app-state \
  --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST --region us-east-1
```

**Catalog management** (no file edit + restart required when using DynamoDB):

```bash
python scripts/manage_virtual_agents.py list
python scripts/manage_virtual_agents.py update --id 1 --name "Updated Travel Agent"
```

**Audit trail** (optional):

```bash
python scripts/audit_webhooks.py list --org-id "$ORG_ID" --limit 10
```

Set `PERSISTENCE_BACKEND=memory` for local dev without DynamoDB (catalog reads from `config/virtual_agents.json` as before).

See `specs/005-persistent-app-state/quickstart.md` for full validation scenarios.

## Virtual agent catalog (Flow Designer)

Webex Contact Center Flow Designer discovers available virtual agents by calling `ListVirtualAgents` on your BYOVA gRPC endpoint. Configure the catalog in `config/virtual_agents.json` (six Cisco demo agents ship by default).

```bash
# Optional: override catalog path
export WEBEX_VIRTUAL_AGENTS_CONFIG=config/virtual_agents.json

# Human-readable discovery logs in the console (recommended for local dev)
export LOG_JSON=false

# List agents (simulates Flow Designer discovery)
grpcurl -plaintext \
  -H 'trackingid: local-test' \
  localhost:50051 \
  com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents
```

When Flow Designer (or grpcurl) requests the agent list, the server logs at **INFO**:

```text
Flow Designer requested virtual agent list — org=n/a agents=6 tracking_id=local-test
```

Edit the catalog via `scripts/manage_virtual_agents.py` (DynamoDB) or `config/virtual_agents.json` when `PERSISTENCE_BACKEND=memory`. Invalid catalogs (duplicate IDs, multiple defaults, empty list) are rejected with a clear error.

Requires `WEBEX_MEDIA_ENABLED=true` and a registered BYODS data source pointing at the gRPC endpoint.

## BYODS data source CRUD (SDK CLI)

After a customer admin authorizes your Service App in Control Hub:

```bash
export ORG_ID="<authorized-org-uuid>"

python scripts/manage_datasources.py list --org-id "$ORG_ID"
python scripts/manage_datasources.py create --org-id "$ORG_ID" --url "https://your-host:50051/grpc"
python scripts/manage_datasources.py get --org-id "$ORG_ID" --id "<data-source-id>"
python scripts/manage_datasources.py update --org-id "$ORG_ID" --id "<id>" --token-lifetime-minutes 720
python scripts/manage_datasources.py delete --org-id "$ORG_ID" --id "<id>"
python scripts/manage_datasources.py schemas list --org-id "$ORG_ID"
```

The CLI bootstraps Integration tokens and fetches org-scoped Service App tokens via the SDK.

## Deploy to AWS (webhooks + gRPC media)

See **[infra/AWS_DEPLOYMENT.md](infra/AWS_DEPLOYMENT.md)** for the full CDK/ECS setup, public URLs, webhook registration, and BYODS data source URLs (`https://media.atozbuildingcrm.com/grpc`).

## Deploy to Render (webhooks + health)

Render exposes HTTP only—use it for webhooks and health checks. Set `WEBEX_MEDIA_ENABLED=false` on Render if you host gRPC media elsewhere.

1. Push repo to GitHub
2. Create Web Service from [`render.yaml`](render.yaml)
3. Set environment variables (see `.env.example`)
4. Run `scripts/register_webhooks.py` locally to obtain `WEBEX_INTEGRATION_REFRESH_TOKEN`

## Deploy with Docker (HTTP + gRPC media)

```bash
docker compose up --build
curl http://localhost:8000/health
```

Expose port `50051` (or `WEBEX_MEDIA_PORT`) publicly for WxCC media. Set `WEBEX_DATASOURCE_PUBLIC_URL` when the gRPC host differs from the webhook URL.

## One-time: OAuth and webhook registration

**Local development** (redirect URI `http://127.0.0.1:8765/callback`):

```bash
export WEBEX_WEBHOOK_TARGET_URL=https://<your-service>/webhooks/webex
python scripts/register_webhooks.py
```

Optionally copy the Integration refresh token into `.env` as bootstrap until you use the production callback.

**Production** (HTTPS redirect URI on the deployed server):

1. Set `WEBEX_INTEGRATION_REDIRECT_URI` and register the same URL in the Webex developer portal.
2. Run `python scripts/register_webhooks.py` to print the authorize URL, or start OAuth from the portal.
3. Complete consent in a browser; tokens persist to DynamoDB automatically.
4. Remove `WEBEX_INTEGRATION_REFRESH_TOKEN` from deployment env after OAuth succeeds.

## Media configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBEX_MEDIA_ENABLED` | `true` | Start SDK media server in-process |
| `WEBEX_MEDIA_HOST` | `0.0.0.0` | gRPC bind host |
| `WEBEX_MEDIA_PORT` | `50051` | gRPC bind port |
| `WEBEX_MEDIA_VERIFY_TOKENS` | `true` | JWS validation on inbound gRPC |
| `WEBEX_MEDIA_ECHO_ENABLED` | `false` | Echo inbound audio for integration testing |

## Tests

```bash
pytest
```

## Project layout

```text
main.py                 # FastAPI app factory
src/webhooks/           # serviceApp webhook routes
src/byods/              # SDK data source helpers
src/byova/              # SDK media server wiring
scripts/                # register_webhooks.py, manage_datasources.py
```

## References

- [webex-byova on PyPI](https://pypi.org/project/webex-byova/)
- [SDK documentation](https://joezanini.github.io/byova-sdk-python/)
- [Render FastAPI deploy](https://render.com/docs/deploy-fastapi)
