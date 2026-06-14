# Feature Specification: Webex Integration OAuth Callback

**Feature Branch**: `006-webex-oauth-callback`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "Set up an endpoint that listens for a redirect from Webex when a developer sets up the integration monitor for Service App authorized/deauthorized requests. It should respond by implementing an authorization code flow grant and abstract the code from the request and get a fresh set of access token and refresh token. I then want those values managed in the new database."

## Clarifications

### Session 2026-06-13

- Q: Should the server expose an endpoint to initiate Integration OAuth, or is this feature callback-only? → A: Callback only — developer starts OAuth manually via Webex developer portal or existing local script pointed at the production callback URL.
- Q: On startup, which integration token source should the server use when both durable storage and environment variables are present? → A: Durable storage first — use persisted tokens when present; fall back to env var only when storage is empty.
- Q: After integration tokens are persisted, when should service app webhook subscriptions be registered or verified? → A: Automatic on startup when configured, plus manual fallback via existing script or documented operator action for explicit re-registration.
- Q: Should webhooks be registered immediately after a successful OAuth callback, and how should registration behave when webhooks may already exist? → A: When integration tokens are available, list existing webhooks and confirm a sufficient subscription exists; register only if a sufficient webhook for service app authorized/deauthorized events targeting the configured URL does not exist. Applies after successful callback and on startup (verify-first, idempotent).
- Q: If authorization code exchange succeeds but persisting tokens fails, what should the server do? → A: Fail and discard — show failure to developer, do not retain tokens in memory, operator retries OAuth.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Production OAuth Callback for Integration Authorization (Priority: P1)

As a developer deploying this webhook server, when I start Integration OAuth externally (via the Webex developer portal or the existing local authorization script aimed at the production callback URL), Webex redirects my browser to the callback URL hosted by the deployed server. The server completes the authorization code exchange and stores the resulting integration access and refresh tokens in durable storage so I no longer need a local-only callback listener or manual copy-paste of refresh tokens into environment variables.

**Why this priority**: Today, integration authorization relies on a local browser flow (`127.0.0.1:8765/callback`) and manual placement of the refresh token in deployment secrets. Without a production callback endpoint, every new deployment or token rotation requires developer workstation access. This blocks repeatable CI/CD and operator handoff.

**Independent Test**: Configure the Webex Integration redirect URI to point at the deployed callback URL, start OAuth from the developer portal or local script (not a server-side authorize route), complete consent in a browser, and verify the server persists integration tokens and subsequent service app webhook registration succeeds without setting `WEBEX_INTEGRATION_REFRESH_TOKEN` manually.

**Acceptance Scenarios**:

1. **Given** a deployed server with the callback route registered as the Integration redirect URI, **When** a developer completes Webex OAuth consent and Webex redirects with a valid authorization code, **Then** the server exchanges the code for a fresh access token and refresh token and persists them in durable storage.
2. **Given** integration tokens were persisted via the callback flow, **When** the server restarts, **Then** it loads integration tokens from durable storage and can refresh or use them for Webex API operations without requiring a new OAuth consent or environment variable bootstrap.
3. **Given** a callback request arrives without an authorization code or with an invalid/expired code, **When** the server processes the request, **Then** the developer receives a clear, non-technical error outcome and no partial or corrupted token record is written to storage.
4. **Given** a developer re-authorizes the Integration (new OAuth consent), **When** the callback completes successfully, **Then** previously stored integration tokens are replaced atomically with the new token set.

---

### User Story 2 - Uninterrupted Service App Webhook Monitoring (Priority: P2)

As an integration operator, after a developer completes Integration OAuth via the callback endpoint, the server ensures service app authorized/deauthorized webhook subscriptions exist using stored integration credentials—listing existing webhooks first and creating one only when no sufficient subscription is present—so customer org authorization events continue to arrive at `POST /webhooks/webex` without duplicate registrations or unnecessary manual setup.

**Why this priority**: The OAuth callback exists to enable service app lifecycle monitoring. Token persistence alone delivers limited value if webhook registration still requires separate manual scripts or secrets.

**Independent Test**: After completing the callback OAuth flow, confirm the server lists webhooks and creates a subscription only if none exists for the configured target URL and event types—both immediately after callback and on startup. Verify no duplicate webhooks are created on restart. Confirm the registration script still works for explicit re-registration. Verify authorized/deauthorized events from a test org are received at the existing webhook endpoint.

**Acceptance Scenarios**:

1. **Given** valid integration tokens in durable storage and a configured webhook target URL, **When** the server starts or completes a successful OAuth callback, **Then** it lists existing webhooks and registers a service app authorized/deauthorized subscription only if no sufficient webhook exists for the configured target URL.
2. **Given** a sufficient webhook already exists for the configured target URL and event types, **When** startup or post-callback verification runs, **Then** no duplicate webhook is created and processing completes successfully.
3. **Given** an operator needs to re-register webhooks explicitly, **When** they run the existing registration script or documented operator action, **Then** webhook subscriptions are created or verified without requiring a new OAuth consent flow.
4. **Given** integration tokens expire or are near expiry, **When** the server needs to call Webex APIs (including webhook management), **Then** it refreshes tokens using the stored refresh token and updates durable storage with the new token set without developer intervention.
5. **Given** the existing `POST /webhooks/webex` handler, **When** org authorization events arrive after Integration OAuth is complete, **Then** webhook processing behavior is unchanged from the operator's perspective (same acknowledgment, org token handling, and side effects).

---

### User Story 3 - Secure, Operator-Friendly Callback Experience (Priority: P3)

As a developer completing OAuth in a browser, I receive an unambiguous success or failure indication on the callback response page, and integration tokens never appear in URLs, logs, or audit output after the exchange completes.

**Why this priority**: OAuth callbacks are security-sensitive and often performed infrequently; unclear outcomes cause support churn and accidental secret exposure.

**Independent Test**: Complete a successful and a failed OAuth callback; inspect HTTP response bodies, application logs, and audit records; confirm tokens are absent from all operator-visible surfaces.

**Acceptance Scenarios**:

1. **Given** a successful authorization code exchange, **When** the developer's browser lands on the callback URL, **Then** they see a success confirmation that does not display access or refresh token values.
2. **Given** any callback processing attempt, **When** structured logs or audit records are written, **Then** authorization codes, access tokens, and refresh tokens are never logged in plaintext.
3. **Given** a callback request includes OAuth error parameters from Webex (user denied consent, invalid client), **When** the server handles the redirect, **Then** the developer sees a actionable failure message without exposing internal configuration details.

---

### Edge Cases

- What happens when durable storage is unavailable during callback processing? Token exchange with Webex may succeed, but if persistence fails the developer sees a failure response, tokens are discarded (not held in memory), and the operator must retry OAuth once storage is available. The server must not report success or leave integration state inconsistent.
- What happens when two developers initiate OAuth concurrently? Only the most recently persisted token set is authoritative; concurrent callbacks should not corrupt storage or produce interleaved token fields.
- What happens when the authorization code is replayed? The second attempt fails gracefully with a clear error; storage retains the valid token set from the first successful exchange.
- What happens when integration tokens are revoked in the Webex developer portal? Subsequent API and webhook operations fail with actionable logs; the operator must re-run OAuth via the callback URL.
- What happens when the deployment still has `WEBEX_INTEGRATION_REFRESH_TOKEN` set in environment variables? Durable storage takes precedence when populated; the env var is used only when storage is empty. Operators should remove stale env vars after successful OAuth callback to avoid confusion, but they do not override persisted tokens.
- What happens when a sufficient webhook already exists? Verification succeeds without creating a duplicate; subsequent startups and post-callback checks remain idempotent.
- What happens when an existing webhook targets a different URL than configured? Treated as insufficient; a new webhook is registered for the configured target (exact handling of stale webhooks deferred to planning).
- What happens if the callback URL is hit by scanners or bots without a valid code? Requests are rejected safely with no token writes and no secret leakage in responses.

## Requirements *(mandatory)*

### Functional Requirements

#### OAuth callback endpoint (P1)

- **FR-001**: System MUST expose an HTTPS-accessible callback route that accepts Webex OAuth redirect requests containing an authorization code query parameter.
- **FR-002**: System MUST extract the authorization code from the incoming redirect request and exchange it for a new integration access token and refresh token through the standard Webex OAuth authorization code grant, without custom protocol reimplementation.
- **FR-003**: System MUST persist the resulting integration access token, refresh token, and expiry metadata in the same durable store used for application state (feature 005), protected at rest with encryption equivalent to org-scoped token storage. If persistence fails after a successful token exchange, system MUST report failure to the developer, discard the token set (no in-memory retention), and leave prior stored tokens unchanged.
- **FR-004**: System MUST load persisted integration tokens on startup so the server operates without requiring `WEBEX_INTEGRATION_REFRESH_TOKEN` in environment variables when durable storage contains a valid token set.
- **FR-004a**: When both durable storage and `WEBEX_INTEGRATION_REFRESH_TOKEN` are present on startup, system MUST use durable storage tokens; env var is fallback only when storage is empty.
- **FR-005**: System MUST atomically replace stored integration tokens when a new successful OAuth callback completes (re-authorization).
- **FR-006**: System MUST return a browser-friendly success or failure response after callback processing so developers know whether authorization completed without reading server logs.
- **FR-007**: System MUST reject callback requests missing a code or containing OAuth error parameters from Webex, with clear developer-facing failure responses and no token persistence.
- **FR-015**: System MUST NOT expose a server-side route that initiates Integration OAuth (redirect to Webex authorize URL); OAuth consent is started externally via the Webex developer portal or the existing local authorization script configured to use the production callback URL.

#### Token lifecycle and webhook enablement (P2)

- **FR-008**: System MUST refresh integration access tokens using the stored refresh token when expired or near expiry, updating durable storage with the new token set.
- **FR-009**: When integration tokens are available in durable storage and a webhook target URL is configured, system MUST list existing webhooks on startup and after successful OAuth callback, confirm whether a sufficient service app authorized/deauthorized subscription exists for the configured target URL, and register one only if none exists.
- **FR-009a**: A **sufficient webhook** is one that monitors service app authorized and deauthorized events and delivers them to the configured webhook target URL (matching current integration monitor semantics).
- **FR-009b**: System MUST also support explicit webhook re-registration via the existing registration script or documented operator action without requiring a new OAuth consent flow.
- **FR-010**: System MUST preserve existing `POST /webhooks/webex` authorization and deauthorization behavior; this feature adds Integration OAuth infrastructure alongside—not in place of—the current webhook handler.

#### Security and observability (P3)

- **FR-011**: System MUST NOT log, audit, or return authorization codes, access tokens, or refresh tokens in plaintext on any operator-visible surface after processing completes.
- **FR-012**: System SHOULD validate OAuth state (or equivalent CSRF protection) when the authorization flow provides a state parameter, rejecting mismatched callbacks.
- **FR-013**: System MUST continue structured logging for callback attempts with request correlation identifiers and outcome (success/failure) without secret values.
- **FR-014**: Integration OAuth client ID and client secret MUST remain in environment variables or managed secrets only—they MUST NOT be stored in the durable token table.

### Key Entities *(include if feature involves data)*

- **Integration OAuth Tokens**: Deployment-scoped credentials (access token, refresh token, expiry metadata) used to call Webex APIs on behalf of the developer Integration—not org-scoped service app tokens. At most one active token set per deployment. Replaced on re-authorization.
- **OAuth Callback Event**: An inbound redirect from Webex carrying either an authorization code, OAuth error parameters, or neither. Processed once; codes are single-use. Not persisted long-term beyond optional audit metadata (no secrets).
- **Webhook Subscription Context**: The configured target URL and resource types (service app authorized/deauthorized) that integration credentials enable once OAuth is complete. A **sufficient webhook** matches the target URL and event types; verification is list-then-act (register only if insufficient). Existing webhook processing for customer orgs remains separate.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer can complete Integration OAuth entirely through the deployed callback URL and achieve a working webhook-monitored deployment without manually copying a refresh token into environment variables in 100% of guided test runs.
- **SC-002**: After server restart, integration-backed Webex API operations succeed using durable storage alone (no env refresh token) in 100% of test scenarios where valid tokens were previously persisted.
- **SC-003**: Zero plaintext integration access tokens, refresh tokens, or authorization codes appear in application logs or audit output during security review sampling of callback and refresh flows.
- **SC-004**: Invalid or expired authorization codes are rejected with a clear developer-facing outcome 100% of the time without writing corrupted token records.
- **SC-005**: Existing service app webhook processing for authorized/deauthorized org events maintains current operator-visible behavior in regression tests (no breaking changes to `POST /webhooks/webex` outcomes).
- **SC-006**: Integration token refresh updates durable storage within one refresh cycle so subsequent API calls succeed without developer re-authorization in test scenarios simulating token expiry.
- **SC-007**: Repeated startup and post-callback webhook verification creates zero duplicate webhooks when a sufficient subscription already exists, in 100% of idempotency test runs.

## Assumptions

- One Webex Integration and one deployment share a single integration token set; multi-integration or multi-tenant token isolation is out of scope for v1.
- Feature 005 (persistent application state) is available or will complete first; this feature extends durable storage to include integration-level OAuth tokens, superseding feature 005's assumption that integration refresh tokens remain environment-only.
- Developers register the production callback URL as a redirect URI on the Webex Integration in the developer portal; URI registration steps are documented in quickstart but not automated by this feature.
- OAuth consent is initiated externally (Webex developer portal or local `register_webhooks.py`-style script with production callback URL); no server-side authorize/start route is in scope for v1.
- The `webex-byova` SDK provides authorization code exchange and refresh capabilities for Integration OAuth; implementation delegates to SDK methods rather than custom HTTP clients.
- OAuth consent is performed manually by a trusted developer in a browser; machine-to-machine client credentials flow is out of scope.
- HTTPS termination is provided by the deployment platform (load balancer, reverse proxy, or PaaS); the callback route assumes TLS in production.
- Environment variable `WEBEX_INTEGRATION_REFRESH_TOKEN` remains supported as bootstrap fallback when durable storage is empty; once tokens are persisted via callback, storage takes precedence on all subsequent startups regardless of env var presence.
- Because OAuth is initiated externally, CSRF `state` validation is best-effort when a state parameter is present (FR-012); absence of state on externally initiated flows is an accepted v1 limitation documented in quickstart.

## Constitution Alignment *(mandatory for BYODS Webhook Server)*

Verify this spec complies with `.specify/memory/constitution.md`:

- **SDK-First**: Authorization code exchange, token refresh, and webhook registration MUST delegate to the `webex-byova` SDK; the callback endpoint orchestrates SDK calls—it does not reimplement Webex OAuth protocols.
- **Webhook Integrity**: Existing `POST /webhooks/webex` flow is preserved. This feature adds a separate Integration OAuth callback route for developer authorization; no rewrite of service app webhook handling is authorized.
- **Modular boundaries**: OAuth callback routing aligns with the webhook/auth module boundary; token persistence extends the shared persistence layer from feature 005 without leaking storage details into BYOVA media modules.
- **Production ops**: Callback endpoint is externally exposed and must appear in health/readiness considerations; structured logging with request IDs; redirect URI and webhook target URL are environment-configured.
- **Security**: Tokens encrypted at rest; secrets (client ID/secret) in env only; no token leakage in logs or callback HTML; rate limiting on public HTTP surfaces applies to the new callback route.
- **Delivery order**: Builds on feature 005 persistence and feature 001 webhook foundation; config → Integration OAuth callback → token persistence → webhook registration verification → tests.
