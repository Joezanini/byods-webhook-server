# Contract: Virtual Agent Catalog & Discovery Logging

**Feature**: `002-virtual-agent-catalog` | **SDK**: `webex-byova[media]>=0.3.0` (catalog support; 0.2.0 returns empty list)

Documents catalog loading, gRPC discovery behavior, and console observability. Protocol implementation remains SDK-internal.

---

## Catalog file contract

**Path**: `WEBEX_VIRTUAL_AGENTS_CONFIG` (default `config/virtual_agents.json`)

**Schema**: JSON array of objects:

```json
[
  {
    "virtual_agent_id": 1,
    "virtual_agent_name": "Travel Booking Agent",
    "is_default": false
  }
]
```

| Field | Type | Rules |
|-------|------|-------|
| `virtual_agent_id` | number or string | Required; unique; coerced to string in gRPC response |
| `virtual_agent_name` | string | Required; non-empty |
| `is_default` | boolean | Optional; default `false`; max one `true` per file |

**Startup errors** (process exit before media bind):

| Condition | Exit behavior |
|-----------|---------------|
| File missing | stderr: path + hint to copy sample |
| Invalid JSON | stderr: parse error + path |
| Duplicate IDs | stderr: duplicate id values |
| Multiple defaults | stderr: list conflicting entries |
| Empty array | stderr: catalog must contain at least one agent |

---

## Application module: `src/byova/catalog.py`

| Function | Responsibility |
|----------|----------------|
| `load_catalog(path: str) -> list[VirtualAgentCatalogEntry]` | Read JSON, coerce IDs to string, validate |
| `to_sdk_config(entries) -> list[VirtualAgentConfig]` | Map to SDK model for `MediaServerConfig` |

Used by `src/byova/server.py` when constructing `BYOVAMediaServer`.

---

## SDK: `ListVirtualAgents` (delegated)

**RPC**: `com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents`

**Request** (`ListVARequest`):

| Field | Type |
|-------|------|
| `customer_org_id` | string |
| `is_default_virtual_agent_enabled` | bool |

**Response** (`ListVAResponse`):

| Field | Type |
|-------|------|
| `virtual_agents[]` | `VirtualAgentInfo` |
| `virtual_agents[].virtual_agent_id` | string |
| `virtual_agents[].virtual_agent_name` | string |
| `virtual_agents[].is_default` | bool |

**Probe** (local validation):

```bash
grpcurl -plaintext localhost:50051 list
grpcurl -plaintext localhost:50051 com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents
```

When `WEBEX_MEDIA_VERIFY_TOKENS=true`, include `-H 'authorization: Bearer <JWS>'` for authenticated calls.

---

## SDK event: `list_virtual_agents` (new in >=0.3.0)

Dispatched from SDK `ListVirtualAgents` handler before returning response.

| Event type | `ListVirtualAgentsEvent` |
|------------|--------------------------|
| Fields | `customer_org_id`, `is_default_virtual_agent_enabled`, `agent_count`, `tracking_id`, `agent_names` |

**Application handler** (`src/byova/handlers.py` or `src/byova/discovery.py`):

```python
@server.on("list_virtual_agents")
async def on_list_virtual_agents(event: ListVirtualAgentsEvent) -> None:
    log_event(
        logger,
        logging.INFO,
        f"Flow Designer requested virtual agent list — org={event.customer_org_id or 'n/a'} "
        f"agents={event.agent_count} tracking_id={event.tracking_id or 'n/a'}",
        operation="list_virtual_agents",
        outcome="success",
        org_id=event.customer_org_id,
    )
```

Extend `log_event` / `StructuredJsonFormatter` to include optional `agent_count`, `tracking_id`, `agent_names` when present.

---

## SDK event: `session_start` (extended metadata)

`SessionStartEvent.metadata` MUST include (SDK >=0.3.0):

| Key | Source |
|-----|--------|
| `virtual_agent_id` | `VoiceVARequest.virtual_agent_id` |
| `customer_org_id` | `VoiceVARequest.customer_org_id` |

Application logs at INFO:

```text
Media session started — conversation_id=... virtual_agent_id=... customer_org_id=...
```

If `virtual_agent_id` not in catalog → WARNING with `operation=session_start`, `outcome=warning`.

---

## Factory change: `src/byova/server.py`

```python
def create_media_server(settings: Settings) -> BYOVAMediaServer:
    catalog = load_catalog(settings.virtual_agents_config_path)
    config = MediaServerConfig.from_env().model_copy(
        update={"virtual_agents": to_sdk_config(catalog)}
    )
    return BYOVAMediaServer(config)
```

---

## Settings addition: `src/config/settings.py`

| Field | Env var | Default |
|-------|---------|---------|
| `virtual_agents_config_path` | `WEBEX_VIRTUAL_AGENTS_CONFIG` | `config/virtual_agents.json` |

---

## Unchanged contracts (FR-011)

- `POST /webhooks/webex` — no changes
- `scripts/manage_datasources.py` — no changes
- `GET /health`, `GET /ready` — no changes
