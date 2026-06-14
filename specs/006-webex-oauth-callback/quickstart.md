# Quickstart: Webex Integration OAuth Callback

**Feature**: `006-webex-oauth-callback` | **Branch**: `006-webex-oauth-callback`

End-to-end validation for production OAuth callback, durable integration tokens, and idempotent webhook registration. See [data-model.md](./data-model.md) and [contracts/](./contracts/).

**Depends on**: Feature 005 persistence (DynamoDB table, encryption key).

---

## Prerequisites

- Python 3.11+ venv with `pip install -r requirements.txt`
- Webex Integration with scopes: `spark:all`, `spark:applications_token`, `application:webhooks_write`, `application:webhooks_read`
- Webex Service App credentials in `.env`
- DynamoDB Local or deployed `byods-app-state` table
- Public HTTPS URL for production callback (ngrok acceptable for local validation)

---

## 1. Configure environment

```bash
cp .env.example .env
```

Set persistence (from [005 quickstart](../005-persistent-app-state/quickstart.md)):

```bash
PERSISTENCE_BACKEND=dynamodb
DYNAMODB_TABLE_NAME=byods-app-state
PERSISTENCE_ENCRYPTION_KEY=<fernet-key>
AWS_REGION=us-east-1
# AWS_ENDPOINT_URL=http://localhost:8001   # DynamoDB Local
```

Set OAuth callback (production example):

```bash
WEBEX_INTEGRATION_CLIENT_ID=...
WEBEX_INTEGRATION_CLIENT_SECRET=...
WEBEX_INTEGRATION_REDIRECT_URI=https://your-host.example.com/oauth/webex/callback
WEBEX_WEBHOOK_TARGET_URL=https://your-host.example.com/webhooks/webex
# Leave unset for first run (or remove after OAuth):
# WEBEX_INTEGRATION_REFRESH_TOKEN=
```

Register `WEBEX_INTEGRATION_REDIRECT_URI` in the [Webex Developer Portal](https://developer.webex.com/) under your Integration's redirect URIs.

---

## 2. Start server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Before OAuth, readiness may fail integration check:

```bash
curl -s http://localhost:8000/health   # {"status":"ok"}
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ready   # 503 until tokens exist
```

---

## 3. P1 — Complete OAuth via production callback (SC-001)

**Option A — Local script with production redirect URI**

Temporarily set redirect URI to production URL, then open authorization URL manually:

```bash
python - <<'PY'
import asyncio, os
from dotenv import load_dotenv
from webex_byova import BYOVA
load_dotenv()
async def main():
    sdk = BYOVA.from_env()
    url, state = sdk.integration.get_authorization_url()
    print("Open in browser:\n", url)
    print("state:", state)
    await sdk.aclose()
asyncio.run(main())
PY
```

Complete consent in browser → Webex redirects to `GET /oauth/webex/callback?code=...`.

**Option B — Webex developer portal**

Start Integration authorization from the portal using the registered production redirect URI.

**Verify**:
- Browser shows success HTML (no token values)
- Server logs show `oauth_callback` success
- DynamoDB item exists: `PK=INTEGRATION`, `SK=CREDS`
- `curl -s http://localhost:8000/ready` → `{"status":"ok"}` without `WEBEX_INTEGRATION_REFRESH_TOKEN`

---

## 4. P1 — Restart persistence (SC-002)

1. Stop and restart `uvicorn` (remove or ignore `WEBEX_INTEGRATION_REFRESH_TOKEN`).
2. Confirm `/ready` returns 200 using storage-only bootstrap.
3. Confirm logs show integration refresh from stored tokens, not env var.

---

## 5. P2 — Webhook idempotency (SC-007)

1. Note webhook count in Webex developer portal (or via SDK list).
2. Restart server twice with `WEBEX_WEBHOOK_TARGET_URL` set.
3. Confirm no duplicate `serviceApp` authorized/deauthorized webhooks for the same target URL.
4. Re-run OAuth callback (re-consent) → verify webhooks still not duplicated.

Manual fallback:

```bash
python scripts/register_webhooks.py
```

Should verify/create webhooks without new OAuth when tokens exist.

---

## 6. P3 — Security checks (SC-003, SC-004)

**Invalid callback**:

```bash
curl -s "http://localhost:8000/oauth/webex/callback"
curl -s "http://localhost:8000/oauth/webex/callback?code=invalid"
```

Expect HTML error responses; no DynamoDB token changes.

**Log review**: Grep logs for access tokens, refresh tokens, authorization codes — expect zero matches in plaintext.

**OAuth denial**: Use portal flow and deny consent → expect failure HTML with `error=access_denied`.

---

## 7. Regression — Service app webhooks (SC-005)

1. With integration ready, authorize a test org via Control Hub.
2. Confirm `POST /webhooks/webex` processes `authorized` event as before feature 006.
3. Deauthorize → confirm org credentials removed from DynamoDB (feature 005 behavior).

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Token exchange fails | `WEBEX_INTEGRATION_REDIRECT_URI` matches portal exactly (scheme, host, path) |
| Persistence failure after exchange | DynamoDB reachable; `PERSISTENCE_ENCRYPTION_KEY` set; failure HTML shown |
| `/ready` 503 after OAuth | Inspect `INTEGRATION/CREDS` item; check integration refresh logs |
| Duplicate webhooks | Should not occur with `aensure`; list webhooks and delete stale URLs manually |
| Stale env token confusion | Remove `WEBEX_INTEGRATION_REFRESH_TOKEN` after successful callback (storage takes precedence) |

---

## Production deployment notes

- Set `WEBEX_INTEGRATION_REDIRECT_URI` to public HTTPS callback URL in ECS/Render env and Webex portal.
- ALB/ingress must route callback path to FastAPI service.
- Integration tokens live in DynamoDB; env refresh token optional for bootstrap only.

See [infra/AWS_DEPLOYMENT.md](../../infra/AWS_DEPLOYMENT.md) after implementation updates.
