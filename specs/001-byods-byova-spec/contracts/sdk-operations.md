# SDK Operations Contract: BYODS CRUD & BYOVA Media

**Feature**: `001-byods-byova-spec` | **Tool**: `webex-byova[media]>=0.2.0` only

All Webex integration is performed through the SDK. There is no operator REST API. This contract documents CRUD script operations, media server wiring, and SDK method mapping.

---

## Prerequisites

| Requirement | Source |
|-------------|--------|
| Integration credentials | `WEBEX_INTEGRATION_CLIENT_ID`, `WEBEX_INTEGRATION_CLIENT_SECRET` |
| Service App credentials | `WEBEX_SA_CLIENT_ID`, `WEBEX_SA_CLIENT_SECRET` |
| Integration refresh token | `WEBEX_INTEGRATION_REFRESH_TOKEN` |
| Authorized org | Customer admin authorized Service App in Control Hub |

**Bootstrap sequence** (every script invocation):

```python
sdk = BYOVA.from_env()
await sdk.integration.arefresh(refresh_token)
await sdk.service_app.afetch_token_for_org(org_id)
client = await sdk.aget_client_for_org(org_id)
```

---

## Script: `scripts/manage_datasources.py`

### `list --org-id <uuid>`

| SDK call | `await client.data_sources.alist()` |
| Returns | List of `DataSourceListItem`; script resolves full URL via `aget` when needed |
| Errors | `OrgNotRegisteredError` → exit 1, message "org not authorized" |

### `get --org-id <uuid> --id <data_source_id>`

| SDK call | `await client.data_sources.aget(data_source_id)` |
| Returns | `DataSource` JSON to stdout |
| Errors | `NotFoundError` → exit 1 |

### `create --org-id <uuid> [--url URL] [--schema-id UUID] ...`

| SDK call | `await client.data_sources.acreate(DataSourceCreate(...))` |
| Pre-check | `service.url_exists(client, url)` — reject duplicate URL (FR-008) |
| Defaults | From env: `WEBEX_DATASOURCE_*` vars (same as webhook auto-register) |
| Returns | Created `DataSource` JSON |
| Errors | Duplicate URL → exit 2; validation → exit 1 |

### `update --org-id <uuid> --id <data_source_id> [--field value]...`

| SDK call | `await client.data_sources.aupdate(id, DataSourceUpdate(...))` |
| Returns | Updated `DataSource` JSON |

### `delete --org-id <uuid> --id <data_source_id>`

| SDK call | `await client.data_sources.adelete(data_source_id)` |
| Returns | Exit 0 on success |

### `schemas list --org-id <uuid>`

| SDK call | `await client.schemas.alist()` |

### `schemas get --org-id <uuid> --id <schema_id>`

| SDK call | `await client.schemas.aget(schema_id)` |

---

## Shared service: `src/byods/service.py`

Used by webhook auto-register and CLI. Same SDK calls; same duplicate URL guard.

| Function | SDK delegation |
|----------|----------------|
| `list_data_sources(sdk, org_id)` | `aget_client_for_org` → `data_sources.alist` |
| `get_data_source(sdk, org_id, id)` | `data_sources.aget` |
| `create_data_source(sdk, org_id, payload)` | duplicate check → `data_sources.acreate` |
| `update_data_source(sdk, org_id, id, payload)` | `data_sources.aupdate` |
| `delete_data_source(sdk, org_id, id)` | `data_sources.adelete` |
| `url_exists(client, url)` | `alist` + `aget` URL comparison |

---

## Webhook auto-register (server-side)

On `authorized` webhook, server calls `create_data_source` when `WEBEX_AUTO_REGISTER_DATASOURCE=true`. Uses in-process SDK instance with tokens from `ahandle_service_app_webhook`—no separate token fetch needed.

---

## Error handling (FR-009, FR-018)

| Condition | Behavior |
|-----------|----------|
| Org not in storage / not authorized | Clear stderr message; non-zero exit; no other org data exposed |
| SDK `ValidationError` | Print SDK message; exit 1 |
| SDK `AuthenticationError` | Hint to check refresh token; exit 1 |
| Duplicate URL | Exit 2 with "URL already registered" |

---

## Media server: `src/byova/` + SDK `BYOVAMediaServer`

**Install**: `pip install "webex-byova[media]>=0.2.0"`

### Server lifecycle

```python
from webex_byova.media import BYOVAMediaServer

media = BYOVAMediaServer.from_env()  # reads WEBEX_MEDIA_* env vars
await media.start()   # FastAPI lifespan startup
await media.stop()    # FastAPI lifespan shutdown
```

| SDK type | Role |
|----------|------|
| `BYOVAMediaServer` | gRPC server, handler registry, session store |
| `MediaServerConfig` | Host, port, audio, timeouts, `verify_tokens` |
| `MediaSession` | Per-call state (`conversation_id`, `session_id`) |
| `TurnContext` | Per-turn stream (`play_prompt`, `collect_input`, `end_turn`) |

### Environment variables (`MediaServerConfig.from_env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBEX_MEDIA_HOST` | `0.0.0.0` | gRPC bind host |
| `WEBEX_MEDIA_PORT` | `50051` | gRPC bind port |
| `WEBEX_MEDIA_VERIFY_TOKENS` | `true` | JWS validation on inbound gRPC |
| `WEBEX_MEDIA_AUDIO_MODE` | `chunked` | `chunked` or `full` |
| `WEBEX_MEDIA_SAMPLE_RATE` | `8000` | Audio sample rate (Hz) |
| `WEBEX_MEDIA_NO_INPUT_TIMEOUT` | `5.0` | Caller input timeout (seconds) |
| `WEBEX_MEDIA_MAX_SESSION_DURATION` | `3600` | Session TTL (`none` to disable) |
| `WEBEX_MEDIA_TLS_CERT` / `WEBEX_MEDIA_TLS_KEY` | — | Optional mTLS |

### Event handlers (`src/byova/handlers.py`)

Register on the shared `BYOVAMediaServer` instance. Handler signatures accept `event`, `session`, and optional `turn`.

| Event | SDK event type | Application responsibility |
|-------|----------------|---------------------------|
| `session_start` | `SessionStartEvent` | Log `conversation_id`, metadata; FR-015 |
| `audio_input` | `AudioInputEvent` | Log/process inbound audio; optional test echo |
| `turn_started` | `TurnStartedEvent` | Log `turn_id`, `turn_number` |
| `turn_ended` | `TurnEndedEvent` | Log reason |
| `session_end` | `SessionEndEvent` | Log duration, reason; FR-015 |
| `error` | `ErrorEvent` | Log code/message; FR-018 |

Example:

```python
@media.on("session_start")
async def on_session_start(event, session):
    logger.info("media session_start conversation_id=%s", event.conversation_id)

@media.on("audio_input")
async def on_audio_input(event, session, turn):
    # Optional: pass-through for integration testing
    if turn and turn.is_active:
        await turn.play_prompt(audio=event.audio)
```

### gRPC protocol (SDK-internal)

SDK implements `com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent` (`ProcessCallerInput` bidirectional stream). **Do not vendor proto or implement a custom servicer**—delegate entirely to `BYOVAMediaServer`.

### Data source URL alignment

Registered BYODS data source `url` MUST resolve to the public gRPC endpoint WxCC dials. Typically `{WEBEX_DATASOURCE_PUBLIC_URL or webhook origin}{WEBEX_DATASOURCE_PATH_SUFFIX}` matching `WEBEX_MEDIA_PORT` exposure.
