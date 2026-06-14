# Data Model: Persistent Application State

**Feature**: `005-persistent-app-state` | **Date**: 2026-06-13

Extends [001 data model](../001-byods-byova-spec/data-model.md) and [002 catalog model](../002-virtual-agent-catalog/data-model.md). Replaces in-memory SDK token storage and file-backed catalog with DynamoDB-backed persistence.

---

## Storage overview

**Table**: `byods-app-state` (single-table, on-demand billing)

**Key pattern**:

| Entity | PK | SK | TTL |
|--------|----|----|-----|
| Org profile | `ORG#{org_id}` | `PROFILE` | — |
| Org credentials | `ORG#{org_id}` | `CREDS` | — |
| Catalog agent | `CATALOG` | `AGENT#{virtual_agent_id}` | — |
| Catalog meta | `CATALOG` | `META` | — |
| Audit event | `ORG#{org_id}` | `AUDIT#{iso8601}#{uuid}` | `expires_at` |

**GSI** (optional v1): `GSI1` — `PK=AUDIT`, `SK={timestamp}` for cross-org audit listing; defer unless CLI requires it (org-scoped query sufficient for P3).

---

## Customer Organization (persisted profile)

Extends feature 001 **Customer Organization** with durable fields.

| Field | Type | Description |
|-------|------|-------------|
| `org_id` | string (UUID) | Partition key suffix; Webex org identifier |
| `authorization_state` | enum | `authorized` \| `deauthorized` |
| `authorized_at` | datetime \| null | Set on first successful authorization |
| `updated_at` | datetime | Last profile or credential change |

**Validation**:
- `org_id` MUST be non-empty and used as sole scope key for org-scoped reads/writes (FR-005)
- Transition `authorized` → `deauthorized` sets `deauthorized_at`; credentials item deleted
- Idempotent re-authorization updates `authorized_at` only if tokens refreshed

**Relationships**:
- One profile per org (1:1 with credential item when authorized)
- Audit events (1:N) under same org partition

**State machine**:

```text
(none) ──authorized webhook──► authorized (+ CREDS item)
authorized ──deauthorized webhook──► deauthorized (CREDS deleted)
deauthorized ──authorized webhook──► authorized (+ new CREDS)
```

---

## Service App Credentials (per org, encrypted)

Maps to SDK `ServiceAppTokens`; stored only when `authorization_state=authorized`.

| Field | Type | Encrypted | Description |
|-------|------|-----------|-------------|
| `org_id` | string | no | Scope key |
| `access_token` | string | yes | Org-scoped service app access token |
| `refresh_token` | string \| null | yes | If provided by Webex |
| `expires_in` | int | no | Seconds |
| `obtained_at` | datetime | no | SDK token timestamp |
| `token_type` | string | no | Default `Bearer` |
| `ciphertext_version` | int | no | Encryption scheme version for rotation |

**Validation**:
- Written only via SDK `set_service_app_tokens` (webhook or SDK refresh path)
- Deleted via `delete_service_app_tokens` on deauthorization
- NEVER logged or included in audit records (FR-017)

**Storage item**: Same partition as org profile, `SK=CREDS`, attribute `token_blob` (Fernet ciphertext of JSON-serialized token fields).

**Not persisted here**: Integration OAuth tokens (`OAuthTokens`) — remain in-memory per FR-008.

---

## Virtual Agent Catalog Entry (persisted)

Same logical model as feature 002; source moves from JSON file to DynamoDB.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `virtual_agent_id` | string | yes | Stable Flow Designer identifier |
| `virtual_agent_name` | string | yes | Display name |
| `is_default` | boolean | no (default false) | At most one true across catalog |

**Aggregate rules** (FR-011–FR-013):
- ≥1 agent MUST exist after any successful mutation batch
- `virtual_agent_id` unique within catalog
- ≤1 `is_default=true`

**Catalog meta** (`CATALOG` / `META`):

| Field | Type | Description |
|-------|------|-------------|
| `entry_count` | int | Denormalized count for readiness checks |
| `updated_at` | datetime | Last catalog mutation (cache invalidation) |
| `seeded_from_file` | boolean | True if bootstrapped from JSON on first run |

**Lifecycle**:

```text
(empty table at deploy)
    ──(optional seed from config/virtual_agents.json)──► catalog items
    ──(CLI manage_virtual_agents.py)──► CRUD mutations + validation
    ──(ListVirtualAgents read-through)──► discovery response
```

---

## Service App Lifecycle Audit Event (P3)

| Field | Type | Description |
|-------|------|-------------|
| `org_id` | string | Customer org |
| `event_type` | enum | `authorized` \| `deauthorized` \| `processing_failure` |
| `timestamp` | datetime | Event time (UTC) |
| `outcome` | enum | `success` \| `failure` |
| `request_id` | string \| null | HTTP request correlation |
| `detail` | string \| null | Sanitized error summary (no tokens) |
| `expires_at` | epoch seconds | DynamoDB TTL (default +30 days) |

**Validation**:
- MUST NOT contain access_token, refresh_token, or integration secrets (FR-017)
- Written asynchronously after webhook handler completes (success or handled failure)

---

## SDK integration mapping

| SDK type | Persistence |
|----------|-------------|
| `TokenStorage` | `DynamoDBTokenStorage` in `src/persistence/token_storage.py` |
| `ServiceAppTokens` | Encrypted `CREDS` item |
| `InMemoryTokenStorage` (integration slice) | Integration tokens only |
| `VirtualAgentConfig` | Loaded from `CatalogRepository` → passed to `MediaServerConfig` |

---

## Configuration (environment)

| Variable | Default | Description |
|----------|---------|-------------|
| `PERSISTENCE_BACKEND` | `dynamodb` | `dynamodb` \| `memory` (tests/local) |
| `DYNAMODB_TABLE_NAME` | `byods-app-state` | Target table |
| `AWS_REGION` | `us-east-1` | DynamoDB region |
| `AWS_ENDPOINT_URL` | — | DynamoDB Local endpoint (dev) |
| `PERSISTENCE_ENCRYPTION_KEY` | — | Fernet key (32-byte url-safe base64); required for dynamodb backend |
| `PERSISTENCE_AUDIT_TTL_DAYS` | `30` | Audit record retention |
| `WEBEX_VIRTUAL_AGENTS_CONFIG` | `config/virtual_agents.json` | Seed file only (bootstrap); not runtime source of truth after migration |

Integration secrets unchanged: `WEBEX_INTEGRATION_*`, `WEBEX_SA_*`, `WEBEX_INTEGRATION_REFRESH_TOKEN`.

---

## In-memory-only (unchanged)

| Entity | Storage | Notes |
|--------|---------|-------|
| Integration OAuth tokens | SDK in-memory | Refreshed from env on startup |
| Media session / turn state | SDK `ConversationStore` | FR-020 |
| BYODS data source records | WxCC API (authoritative) | FR-021 |
