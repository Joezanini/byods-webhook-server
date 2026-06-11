# Data Model: BYODS CRUD & BYOVA Media Platform

**Feature**: `001-byods-byova-spec` | **Date**: 2026-06-07

This document describes domain entities, in-memory/runtime state, validation rules, and lifecycle transitions. Persistent storage is out of scope (spec assumption: in-memory credentials only).

---

## Customer Organization

| Field | Type | Description |
|-------|------|-------------|
| `org_id` | UUID string | Webex Contact Center tenant identifier |
| `authorization_state` | enum | `authorized` \| `deauthorized` \| `unknown` |
| `authorized_at` | datetime \| null | Set on first successful `authorized` webhook |
| `deauthorized_at` | datetime \| null | Set on `deauthorized` webhook |

**Relationships**:
- Has zero or one active **Service App Credentials** record when authorized
- Has zero or many **Data Source** registrations in WxCC (via SDK)

**Validation**:
- `org_id` MUST be a non-empty UUID string for any BYODS or media operation
- Operations on orgs not in `authorized` state MUST be rejected (FR-009)

**State transitions**:

```text
unknown ──(authorized webhook)──► authorized
authorized ──(deauthorized webhook)──► deauthorized
deauthorized ──(authorized webhook)──► authorized
```

**Storage**: Authorization state is implied by presence of Service App tokens in SDK `InMemoryTokenStorage` (not a separate DB table).

---

## Integration Credentials

| Field | Type | Description |
|-------|------|-------------|
| `client_id` | string | Webex Integration OAuth client ID |
| `client_secret` | string | Integration client secret (env only) |
| `refresh_token` | string | Long-lived refresh token for bootstrap |
| `access_token` | string | Current Integration access token (runtime) |
| `expires_at` | datetime | Integration access token expiry |

**Validation**:
- Required env vars: `WEBEX_INTEGRATION_CLIENT_ID`, `WEBEX_INTEGRATION_CLIENT_SECRET`
- `WEBEX_INTEGRATION_REFRESH_TOKEN` required at runtime for webhook token exchange (FR-020)

**Lifecycle**: Bootstrapped on app startup via `sdk.integration.arefresh()`; refreshed automatically by SDK.

---

## Service App Credentials

| Field | Type | Description |
|-------|------|-------------|
| `org_id` | UUID string | Scoped organization |
| `access_token` | string | Org-scoped Service App token |
| `refresh_token` | string \| null | If provided by Webex |
| `expires_in` | int | Token lifetime in seconds |
| `expires_at` | datetime | Computed expiry |

**Validation**:
- Created only via successful `authorized` webhook handling (`sdk.ahandle_service_app_webhook`)
- Removed on `deauthorized` webhook

**Storage**: SDK `InMemoryTokenStorage` — lost on process restart (documented limitation).

---

## Data Source

Maps to SDK model `webex_byova.models.datasource.DataSource`.

| Field | Type | Required on create | Mutable | Description |
|-------|------|-------------------|---------|-------------|
| `id` | string | — (server-assigned) | no | WxCC data source ID |
| `schema_id` | UUID string | yes | yes | BYODS schema UUID |
| `url` | HTTPS URL | yes | yes | Public ingestion endpoint (must match gRPC/media URL) |
| `audience` | string | yes | yes | Virtual agent audience (e.g. `BYOVAGateway`) |
| `subject` | string | yes | yes | Data subject (e.g. `callAudioData`) |
| `nonce` | string | yes | yes | Unique nonce for registration |
| `token_lifetime_minutes` | int | yes | yes | JWS token lifetime |
| `status` | string | — | no (WxCC-managed) | e.g. `active`, `error` |
| `error_message` | string \| null | — | no | Provisioning error detail |

**Validation rules** (FR-004, FR-008, FR-019):
- `url` MUST be HTTPS and match operator-approved Service App domain
- `schema_id` MUST reference a valid schema for the org (verify via `OrgClient.schemas.aget` when operator supplies non-default ID)
- Duplicate `url` within same `org_id` MUST be rejected before `POST`
- `token_lifetime_minutes` MUST be positive integer
- `nonce` MUST be unique per create (server generates UUID if omitted in operator API)

**Relationships**:
- Belongs to one **Customer Organization**
- References one **Data Source Schema**

**Lifecycle**:

```text
(create) ──► provisioning ──► active
                    └──► error (error_message set)
(delete) ──► removed
(update) ──► re-provisioning (status may transition)
```

---

## Data Source Schema

Maps to SDK model `webex_byova.models.schema.Schema`.

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID string | Schema identifier |
| `name` | string | Human-readable name |
| `description` | string \| null | Schema purpose |

**Usage**: Read-only discovery for operators (`GET /api/v1/orgs/{org_id}/schemas`). Default voice VA schema ID documented in config.

---

## Webhook Event

| Field | Type | Description |
|-------|------|-------------|
| `resource` | string | Must be `serviceApp` |
| `event` | string | `authorized` \| `deauthorized` |
| `org_id` | string | Encoded or decoded org identifier from payload |

**Validation** (FR-001, FR-018):
- Invalid resource or event → HTTP 400, no state change
- Integration auth failure → HTTP 503, no credential corruption
- Idempotent: duplicate `authorized` for same org MUST NOT create duplicate data sources (same URL)

**Processing outcomes**:
- `authorized` → store Service App tokens; optionally auto-register data source
- `deauthorized` → delete Service App tokens for org

---

## Media Session

Maps to SDK `webex_byova.media.session.MediaSession` and `TurnContext`. Managed by SDK `BYOVAMediaServer` and `ConversationStore`—no custom session registry in this repo.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `conversation_id` | string | WxCC / gRPC request | Long-lived call key |
| `session_id` | UUID string | SDK-generated | Per-session identifier |
| `state` | `SessionState` | SDK enum | `active` \| `ending` \| `ended` |
| `turn_count` | int | SDK | Turns within session |
| `metadata` | dict | `SessionStartEvent` | Org/context from WxCC |
| `started_at` | datetime | SDK | Session start time |

**Turn context** (`TurnContext`):

| Field | Type | Description |
|-------|------|-------------|
| `turn_id` | string | Unique turn identifier |
| `turn_number` | int | 1-based index within session |
| `is_active` | bool | Stream open |
| `is_final` | bool | Turn closed with RESPONSE_FINAL |

**Validation** (FR-010–FR-013):
- gRPC auth via SDK `MediaServerConfig.verify_tokens` + `JWSVerifier`
- Session isolation via SDK `ConversationStore` (FR-012)
- Idle/max duration via `WEBEX_MEDIA_MAX_SESSION_DURATION`

**State transitions** (SDK-managed):

```text
SESSION_START ──► active (MediaSession created)
active ──► turn_started ──► audio_input / dtmf_input ──► turn_ended
active ──► session_end ──► ended
error ──► ending ──► ended
```

**Application handlers** (`src/byova/handlers.py`): Log lifecycle events; optional test pass-through on `audio_input`—no custom protocol logic.

---

## SDK Script Invocation Context

| Field | Type | Description |
|-------|------|-------------|
| `org_id` | UUID string | Target org for CRUD script |
| `operation` | string | `list`, `get`, `create`, `update`, `delete`, `schemas` |

Used for structured logging in `scripts/manage_datasources.py`; not persisted. Auth via SDK `integration.arefresh` + `service_app.afetch_token_for_org`.

---

## Entity Relationship Summary

```text
Integration Credentials (1 per deployment)
        │
        ▼
Service App Credentials (0..N orgs, in-memory)
        │
        ├──► Customer Organization (authorization state)
        │         │
        │         ├──► Data Source (0..N, WxCC API via SDK)
        │         │         └──► Data Source Schema
        │         │
        │         └──► Media Session (SDK BYOVAMediaServer / ConversationStore)
        │
Webhook Event ──► mutates Service App Credentials (SDK)
SDK CLI / service helpers ──► mutates Data Source (OrgClient)
WxCC gRPC ──► SDK MediaSession lifecycle
```
