# Data Model: Webex Integration OAuth Callback

**Feature**: `006-webex-oauth-callback` | **Date**: 2026-06-13

Extends [005 data model](../005-persistent-app-state/data-model.md). Adds durable integration OAuth token storage and documents callback/webhook verification entities.

---

## Storage overview (additions)

**Table**: `byods-app-state` (same single table as feature 005)

**New key pattern**:

| Entity | PK | SK | TTL |
|--------|----|----|-----|
| Integration OAuth tokens | `INTEGRATION` | `CREDS` | — |

Existing org, catalog, and audit patterns unchanged.

---

## Integration OAuth Tokens (deployment singleton)

Maps to SDK `OAuthTokens`. One active token set per deployment.

| Field | Type | Encrypted | Description |
|-------|------|-----------|-------------|
| `access_token` | string | yes | Integration bearer token for Webex API calls |
| `refresh_token` | string \| null | yes | Long-lived refresh token |
| `expires_in` | int | no | Access token lifetime (seconds) |
| `obtained_at` | datetime | no | When tokens were issued/refreshed |
| `token_type` | string | no | Default `Bearer` |
| `refresh_token_expires_in` | int \| null | no | If provided by Webex |
| `ciphertext_version` | int | no | Fernet scheme version |

**Validation**:
- At most one `INTEGRATION/CREDS` item per table
- Written via `DynamoDBTokenStorage.set_integration_tokens` after successful OAuth callback or SDK `arefresh`
- Replaced atomically on re-authorization (FR-005)
- If persistence fails after exchange, item MUST NOT be partially updated (fail-and-discard)
- NEVER logged or returned in callback HTML (FR-011)

**Storage item**:

```json
{
  "PK": "INTEGRATION",
  "SK": "CREDS",
  "token_blob": "<fernet-ciphertext>",
  "ciphertext_version": 1,
  "updated_at": "2026-06-13T12:00:00Z"
}
```

**Not stored**: Integration `client_id` / `client_secret` (env/secrets only, FR-014).

---

## OAuth Callback Event (transient)

Not persisted as a durable entity. Handled per HTTP request.

| Attribute | Source | Notes |
|-----------|--------|-------|
| `code` | query param | Single-use; exchanged immediately |
| `state` | query param | Optional CSRF token |
| `error` | query param | Webex OAuth denial |
| `error_description` | query param | User-facing failure context |

**Lifecycle**: Request received → validate → exchange (if code) → persist → webhook ensure → HTML response. No long-term storage.

Optional structured log fields: `operation=oauth_callback`, `outcome=success|failure`, `request_id` — no secrets.

---

## Webhook Subscription Context

Logical entity; Webex is system of record for webhook registrations.

| Field | Type | Description |
|-------|------|-------------|
| `target_url` | string (HTTPS) | From `WEBEX_WEBHOOK_TARGET_URL` |
| `resource` | string | `serviceApp` |
| `events` | set | `authorized`, `deauthorized` |

**Sufficient webhook** (FR-009a): For each required event, an existing registration where `resource=serviceApp`, `event` matches, and `target_url` equals configured URL.

**Verification algorithm** (delegated to SDK `aensure_service_app_webhooks`):
1. List webhooks via Integration bearer token
2. For each event in `{authorized, deauthorized}`, check existence for `target_url`
3. Create missing registrations only

**State transitions**:

```text
(no integration tokens) ──OAuth callback + persist──► tokens in INTEGRATION/CREDS
(tokens present) ──startup/post-callback ensure──► webhooks verified (0–2 created if missing)
(tokens present) ──arefresh on expiry──► updated INTEGRATION/CREDS
(re-authorization) ──new OAuth callback──► INTEGRATION/CREDS replaced
(tokens revoked externally) ──API failure──► operator re-runs OAuth (manual)
```

---

## Relationships

```text
INTEGRATION/CREDS (1 per deployment)
    │
    ├── used by IntegrationTokenManager (SDK) for Webex API auth
    │
    └── enables WebhookManager.aensure_service_app_webhooks
            │
            └── delivers events to POST /webhooks/webex
                    │
                    └── org-scoped ORG#/CREDS (feature 005, unchanged)
```

---

## Migration from feature 005

| Before (005) | After (006) |
|--------------|-------------|
| `get/set_integration_tokens` → in-memory only | → DynamoDB `INTEGRATION/CREDS` when `PERSISTENCE_BACKEND=dynamodb` |
| Startup: env `WEBEX_INTEGRATION_REFRESH_TOKEN` only | Storage-first; env fallback when storage empty |
| OAuth via localhost listener only | Production callback route at redirect URI path |

Update [005 persistence contract](../005-persistent-app-state/contracts/persistence-storage.md) integration row during implementation (006 contract is authoritative for integration tokens).
