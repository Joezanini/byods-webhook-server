# Research: Webex Integration OAuth Callback

**Feature**: `006-webex-oauth-callback` | **Date**: 2026-06-13

## R1: OAuth callback route and redirect URI alignment

**Decision**: Register the callback HTTP route at the path component of `WEBEX_INTEGRATION_REDIRECT_URI` (parsed via `urllib.parse.urlparse`). Production example: `https://api.example.com/oauth/webex/callback` → route path `/oauth/webex/callback`. No server-side authorize/start route (clarified).

**Rationale**: Webex validates `redirect_uri` on token exchange must exactly match the registered Integration redirect URI. Parsing from env keeps deployment config single-source and avoids path drift between env and router.

**Alternatives considered**:
- *Fixed hardcoded path* — rejected; breaks when operators use a different registered URI.
- *Server-side authorize endpoint* — rejected per clarification; OAuth started externally.

---

## R2: Authorization code exchange (SDK)

**Decision**: Use `IntegrationTokenManager.aexchange_code(code)` from `webex-byova` SDK. This method POSTs to the Webex token endpoint with `grant_type=authorization_code` and does **not** auto-persist tokens (unlike `aauthorize` which uses local redirect listener + storage).

**Rationale**: Constitution SDK-first requirement. Callback handler orchestrates: extract `code` → `aexchange_code` → explicit `token_storage.set_integration_tokens` → webhook ensure. Matches fail-and-discard semantics when persistence fails (exchange succeeds but storage write fails before any in-memory update).

**Alternatives considered**:
- *Custom httpx token POST* — rejected; duplicates SDK and risks drift from `IntegrationTokenManager._parse_token_response`.
- *Reuse `aauthorize(open_browser=False)`* — rejected; requires local redirect listener, not production callback.

---

## R3: Integration token persistence in DynamoDB

**Decision**: Extend `DynamoDBTokenStorage` to persist integration tokens at `PK=INTEGRATION`, `SK=CREDS` with the same Fernet-encrypted `token_blob` pattern as org credentials. `InMemoryTokenStorage` slice removed for integration when backend is DynamoDB; memory backend keeps full in-memory storage for tests.

**Rationale**: Supersedes feature 005 R2 (integration in-memory only). Single table, one singleton item per deployment, encrypted at rest. `set_integration_tokens` / `get_integration_tokens` perform DynamoDB I/O; `arefresh` already calls `set_integration_tokens` so refresh cycles persist automatically.

**Alternatives considered**:
- *Separate Secrets Manager secret for refresh token* — rejected; spec requires durable store from feature 005; env var remains bootstrap fallback only.
- *Store only refresh token* — rejected; SDK `OAuthTokens` includes access token + expiry; full blob matches org token pattern and supports `aget_access_token` expiry checks.

---

## R4: Startup bootstrap precedence

**Decision**:

1. If `get_integration_tokens()` returns tokens from durable storage → load into SDK storage, call `arefresh()` to validate/refresh, set `integration_ready=True`.
2. Else if `WEBEX_INTEGRATION_REFRESH_TOKEN` env set → `arefresh(refresh_token)` (persists to storage via `set_integration_tokens`), set `integration_ready=True`.
3. Else → `integration_ready=False`, log warning; `/ready` returns 503 until OAuth callback completes.

Durable storage always wins when populated (clarified).

**Rationale**: Meets FR-004/FR-004a; env var becomes one-time migration path for existing deployments.

---

## R5: Webhook verify-first registration

**Decision**: Call SDK `WebhookManager.aensure_service_app_webhooks(target_url)` on startup (when tokens + `WEBEX_WEBHOOK_TARGET_URL` configured) and immediately after successful OAuth callback. SDK already lists webhooks and creates only missing `serviceApp` `authorized`/`deauthorized` entries for the target URL.

**Rationale**: Matches clarified verify-first/idempotent requirement without custom list logic. Aligns with existing `scripts/register_webhooks.py` behavior.

**Stale webhooks** (different target URL): `aensure` does not delete old webhooks; new webhooks are created for the configured URL. Operators may manually delete stale webhooks in developer portal; document in quickstart. No auto-delete in v1 (avoids accidental removal of shared dev integrations).

---

## R6: Callback HTTP response UX

**Decision**: Return `text/html` success/failure pages via FastAPI `HTMLResponse` with minimal static templates (no token values, no stack traces). Log structured outcome with request ID; never log `code`, access token, or refresh token.

**Rationale**: FR-006/FR-011; developer completes flow in browser.

**OAuth error query params** (`error`, `error_description`): Map to user-friendly failure HTML without internal config details.

---

## R7: CSRF `state` parameter

**Decision**: Best-effort validation when `state` query param is present (compare against optional server-side session/cache if local script generated state). When absent (externally initiated portal flow), accept callback without state rejection — documented v1 limitation per spec assumptions.

**Rationale**: Clarification session; callback-only flow often lacks server-issued state.

---

## R8: Persistence failure handling

**Decision**: On callback: `tokens = await aexchange_code(code)` then `await storage.set_integration_tokens(tokens)`. If `set_integration_tokens` raises, return failure HTML; do not update in-memory integration tokens; prior DynamoDB record unchanged.

**Rationale**: Clarified fail-and-discard; prevents silent in-memory-only tokens lost on restart.

---

## R9: `register_webhooks.py` compatibility

**Decision**: Update script to document production callback flow: set `WEBEX_INTEGRATION_REDIRECT_URI` to production HTTPS callback, run script with `open_browser=True` only when redirect URI is localhost; for production, print `get_authorization_url()` for manual browser open. Script continues to call `aensure_service_app_webhooks` for manual re-registration (FR-009b).

**Rationale**: FR-009b manual fallback; script already uses SDK authorize/ensure patterns.

---

## R10: Rate limiting and readiness

**Decision**: Callback route covered by existing `WebhookRateLimitMiddleware` (same limiter as webhooks). `/ready` continues to require `integration_ready`; after first successful OAuth + persist, readiness passes without env refresh token.

**Rationale**: Constitution security/production ops; infrequent OAuth traffic still benefits from abuse protection.
