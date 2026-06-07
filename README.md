# BYODS Webhook Server

Minimal [FastAPI](https://fastapi.tiangolo.com/) service for testing Webex Contact Center **serviceApp** lifecycle webhooks (`authorized`, `deauthorized`) using the [webex-byova](https://pypi.org/project/webex-byova/) SDK. Designed to deploy on [Render](https://render.com/).

## What it does

- `POST /webhooks/webex` — receives and processes serviceApp webhooks via `BYOVA.ahandle_service_app_webhook()`
- `GET /health` — health check for Render

On **authorized**, the SDK fetches and stores Service App tokens for the org (in memory). On **deauthorized**, stored tokens are removed. Events are logged to stdout for inspection in Render's log stream.

## Prerequisites

1. A [Webex Developer](https://developer.webex.com/) account
2. A **Webex Integration** with scopes:
   - `spark:all`
   - `spark:applications_token`
   - `application:webhooks_write`
   - `application:webhooks_read`
3. A **Webex Service App** with BYODS scopes (`spark-admin:datasource_read`, `spark-admin:datasource_write`)
4. Redirect URI registered on the Integration: `http://127.0.0.1:8765/callback`

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Webex credentials
```

## Deploy to Render

1. Push this repo to GitHub (or GitLab/Bitbucket).
2. In Render, create a **Blueprint** or **Web Service** from the repo. The included [`render.yaml`](render.yaml) defines:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Health check: `/health`
3. Set these environment variables in the Render dashboard:

| Variable | Description |
|----------|-------------|
| `WEBEX_INTEGRATION_CLIENT_ID` | Integration client ID |
| `WEBEX_INTEGRATION_CLIENT_SECRET` | Integration client secret |
| `WEBEX_SA_CLIENT_ID` | Service App client ID |
| `WEBEX_SA_CLIENT_SECRET` | Service App client secret |
| `WEBEX_INTEGRATION_REFRESH_TOKEN` | From the local OAuth step below |

4. Deploy and note your service URL, e.g. `https://byods-webhook-server.onrender.com`.

## One-time: OAuth and webhook registration (local)

Run this **locally** after deploying to Render so you have the public HTTPS webhook URL:

```bash
export WEBEX_INTEGRATION_CLIENT_ID=...
export WEBEX_INTEGRATION_CLIENT_SECRET=...
export WEBEX_SA_CLIENT_ID=...
export WEBEX_SA_CLIENT_SECRET=...
export WEBEX_WEBHOOK_TARGET_URL=https://<your-service>.onrender.com/webhooks/webex

python scripts/register_webhooks.py
```

The script will:

1. Open a browser for developer Integration OAuth
2. Print an Integration **refresh token** — copy it into Render as `WEBEX_INTEGRATION_REFRESH_TOKEN` and redeploy
3. Register `authorized` and `deauthorized` webhooks pointing at your Render URL

> **Why the refresh token on Render?** The server uses in-memory token storage. On each deploy/restart, Integration tokens must be reloaded. The `authorized` webhook handler needs a valid Integration access token to fetch Service App tokens for the customer org.

## Test webhook events

1. Confirm the service is healthy: `curl https://<your-service>.onrender.com/health`
2. In Webex Control Hub, have a customer admin **authorize** your Service App
3. Watch Render logs for `serviceApp authorized: org_id=...`
4. **Deauthorize** the Service App and confirm `serviceApp deauthorized: org_id=...` in logs

## Run locally (optional)

```bash
export WEBEX_INTEGRATION_REFRESH_TOKEN=...  # after running register_webhooks.py
uvicorn main:app --reload --port 8000
```

Use a tunnel (e.g. ngrok) if you need a public HTTPS URL for local webhook testing.

## Notes

- **Free tier:** Render free services spin down after inactivity; the first webhook after idle may be delayed by a cold start.
- **Token storage:** Service App tokens are in-memory only and are lost on restart. This is intentional for webhook testing.
- **Non-serviceApp events:** Invalid or unexpected payloads return HTTP 400.

## References

- [webex-byova on PyPI](https://pypi.org/project/webex-byova/)
- [Webhooks guide](https://joezanini.github.io/byova-sdk-python/guides/webhooks/)
- [Render FastAPI deploy docs](https://render.com/docs/deploy-fastapi)
