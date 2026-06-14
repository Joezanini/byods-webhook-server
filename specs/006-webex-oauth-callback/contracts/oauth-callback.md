# Contract: Integration OAuth Callback HTTP

**Feature**: `006-webex-oauth-callback` | **SDK**: `webex-byova` `IntegrationTokenManager.aexchange_code`

Public HTTP surface for Webex Integration OAuth redirect handling. Implementation in `src/webhooks/` (or `src/auth/` if split). No server-side authorize route.

---

## Route registration

**Path**: Parsed from `WEBEX_INTEGRATION_REDIRECT_URI` environment variable (path component only).

| Environment | Example redirect URI | Route |
|-------------|---------------------|-------|
| Local dev (script) | `http://127.0.0.1:8765/callback` | Not mounted on FastAPI (local listener) |
| Production | `https://host.example.com/oauth/webex/callback` | `GET /oauth/webex/callback` |

**Methods**: `GET` only (Webex browser redirect).

**Security**: Covered by `WebhookRateLimitMiddleware`; HTTPS assumed in production (TLS at load balancer).

---

## Request: successful redirect

```http
GET /oauth/webex/callback?code={authorization_code}&state={optional_state} HTTP/1.1
Host: host.example.com
```

| Query param | Required | Description |
|-------------|----------|-------------|
| `code` | yes (success path) | Single-use authorization code |
| `state` | no | CSRF token; validated if present (best-effort) |

---

## Request: OAuth error redirect

```http
GET /oauth/webex/callback?error=access_denied&error_description=...&state=... HTTP/1.1
```

| Query param | Required | Description |
|-------------|----------|-------------|
| `error` | yes (error path) | Webex OAuth error code |
| `error_description` | no | Human-readable denial reason |

---

## Response: success

**Status**: `200 OK`  
**Content-Type**: `text/html; charset=utf-8`

Body: Minimal HTML confirmation (e.g., "Integration authorized successfully. You may close this window."). MUST NOT include access token, refresh token, or authorization code.

**Side effects** (in order):
1. `tokens = await sdk.integration.aexchange_code(code)`
2. `await token_storage.set_integration_tokens(tokens)` — DynamoDB persist; on failure → error response, discard tokens
3. If `WEBEX_WEBHOOK_TARGET_URL` set: `await sdk.webhooks.aensure_service_app_webhooks(target_url)`
4. Structured log: `operation=oauth_callback`, `outcome=success`, `request_id`

---

## Response: failure

**Status**: `400 Bad Request` (invalid/missing code, exchange failure) or `502 Bad Gateway` (persistence failure after exchange)

**Content-Type**: `text/html; charset=utf-8`

Body: Minimal HTML error message suitable for developers. MUST NOT expose client secrets, stack traces, or token values.

**Side effects**: No token persistence on failure; prior `INTEGRATION/CREDS` unchanged.

---

## SDK integration boundary

| Step | SDK call | Custom HTTP |
|------|----------|-------------|
| Code exchange | `integration.aexchange_code(code)` | No |
| Token persist | `token_storage.set_integration_tokens(tokens)` | No (DynamoDB in storage impl) |
| Token refresh (startup) | `integration.arefresh(...)` | No |
| Webhook ensure | `webhooks.aensure_service_app_webhooks(url)` | No |

---

## Startup integration bootstrap

Called from `main.py` lifespan (not HTTP):

```python
stored = await token_storage.get_integration_tokens()
if stored:
    await sdk.integration.arefresh()  # validates + persists refresh
    integration_ready = True
elif settings.integration_refresh_token:
    await sdk.integration.arefresh(settings.integration_refresh_token)
    integration_ready = True
else:
    integration_ready = False
```

Precedence: durable storage first (FR-004a).

Post-bootstrap webhook ensure (when `integration_ready` and `webhook_target_url`):

```python
await sdk.webhooks.aensure_service_app_webhooks(settings.webhook_target_url)
```

---

## Unchanged routes

| Route | Status |
|-------|--------|
| `POST /webhooks/webex` | Unchanged (FR-010) |
| `GET /health` | Unchanged |
| `GET /ready` | Unchanged semantics; passes when integration bootstrapped |

---

## Environment variables

| Variable | Required | Role |
|----------|----------|------|
| `WEBEX_INTEGRATION_CLIENT_ID` | yes | OAuth client |
| `WEBEX_INTEGRATION_CLIENT_SECRET` | yes | OAuth secret (env/secrets only) |
| `WEBEX_INTEGRATION_REDIRECT_URI` | yes | Must match Webex portal; determines callback path |
| `WEBEX_WEBHOOK_TARGET_URL` | recommended | Target for `aensure_service_app_webhooks` |
| `WEBEX_INTEGRATION_REFRESH_TOKEN` | optional | Bootstrap fallback when storage empty |
| `PERSISTENCE_BACKEND` | yes (prod) | `dynamodb` for durable integration tokens |
| `PERSISTENCE_ENCRYPTION_KEY` | yes (dynamodb) | Fernet key for token blob |

See [persistence extension contract](./persistence-integration-tokens.md) for DynamoDB item schema.
