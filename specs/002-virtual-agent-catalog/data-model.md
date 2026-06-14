# Data Model: Virtual Agent Catalog for Flow Designer

**Feature**: `002-virtual-agent-catalog` | **Date**: 2026-06-08

Extends [001 data model](../001-byods-byova-spec/data-model.md). No new persistent storage; catalog is file-backed and loaded into memory at startup.

---

## Virtual Agent Catalog Entry

Maps to SDK `VirtualAgentConfig` (planned `webex-byova>=0.3.0`) and Cisco reference JSON.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `virtual_agent_id` | string | yes | Stable identifier advertised to WxCC (JSON may use int; normalized to string at load) |
| `virtual_agent_name` | string | yes | Human-readable name shown in Flow Designer picker |
| `is_default` | boolean | no (default `false`) | Marks the default agent when WxCC requests default-enabled lists |

**Validation rules** (FR-004, FR-005):
- `virtual_agent_id` MUST be unique within the catalog
- `virtual_agent_name` MUST be non-empty after trim
- At most one entry MAY have `is_default: true`
- Catalog MUST contain at least one entry at startup (FR-009)

**Example** (shipped sample):

```json
[
  {
    "virtual_agent_id": 1,
    "virtual_agent_name": "Travel Booking Agent",
    "is_default": false
  }
]
```

---

## Virtual Agent Catalog (aggregate)

| Field | Type | Description |
|-------|------|-------------|
| `entries` | list[VirtualAgentCatalogEntry] | Ordered list as defined in config file |
| `source_path` | string | Resolved filesystem path from `WEBEX_VIRTUAL_AGENTS_CONFIG` |
| `loaded_at` | datetime | Server startup timestamp |

**Relationships**:
- Loaded once at BYOVA media server startup
- Passed into `MediaServerConfig.virtual_agents` for SDK `ListVirtualAgents`
- Referenced by session handlers to validate inbound `virtual_agent_id`

**Lifecycle**:

```text
(config file on disk)
    ──(startup load + validate)──► in-memory catalog
    ──(ListVirtualAgents RPC)──► Agent Discovery Response
    ──(ProcessCallerInput)──► Session Agent Context
```

**State transitions**: Immutable until process restart (hot-reload out of scope).

---

## Agent Discovery Response

Runtime gRPC message `ListVAResponse` (SDK-internal). Logical fields exposed to WxCC/Flow Designer:

| Field | Type | Description |
|-------|------|-------------|
| `virtual_agents[]` | repeated | Full catalog at discovery time |
| `virtual_agents[].virtual_agent_id` | string | Agent identifier |
| `virtual_agents[].virtual_agent_name` | string | Display name |
| `virtual_agents[].is_default` | boolean | Default flag |

**Request context** (`ListVARequest`):

| Field | Type | Logged | Description |
|-------|------|--------|-------------|
| `customer_org_id` | string | yes | Org Flow Designer is configuring (may be empty in grpcurl tests) |
| `is_default_virtual_agent_enabled` | boolean | yes | Whether client wants default agent metadata |

**gRPC metadata** (optional, logged when present):

| Key | Description |
|-----|-------------|
| `trackingid` | WxCC correlation ID (Cisco sample reads this) |
| `authorization` | Bearer JWS when `WEBEX_MEDIA_VERIFY_TOKENS=true` |

---

## List Virtual Agents Discovery Event (observability)

Application-level log record emitted on each `ListVirtualAgents` RPC (user-requested console logging).

| Field | Type | Description |
|-------|------|-------------|
| `operation` | string | Always `list_virtual_agents` |
| `outcome` | string | `success` or `failure` |
| `customer_org_id` | string \| null | From `ListVARequest` |
| `is_default_virtual_agent_enabled` | boolean | From request |
| `agent_count` | int | Number of agents returned |
| `agent_names` | list[string] | Display names returned (for console readability) |
| `tracking_id` | string \| null | From gRPC metadata `trackingid` |
| `message` | string | Human-readable summary for plain console mode |

**Log level**: INFO (always visible in default console configuration).

---

## Session Agent Context

Extends existing `MediaSession` / `SessionStartEvent` from feature `001`.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `virtual_agent_id` | string \| null | `VoiceVARequest.virtual_agent_id` | Agent selected in Flow Designer for this call |
| `customer_org_id` | string \| null | `VoiceVARequest.customer_org_id` | Caller org |
| `conversation_id` | string | `VoiceVARequest.conversation_id` | WxCC conversation identifier |
| `catalog_match` | boolean | application | `true` if `virtual_agent_id` exists in loaded catalog |

**Validation on session_start**:
- If `virtual_agent_id` is set and not in catalog → log WARNING, set `catalog_match=false`, continue session (graceful fallback per spec P3 scenario 3)
- If `virtual_agent_id` is empty → log INFO noting missing selection; handlers use optional default agent if one is configured

---

## Configuration (environment)

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBEX_VIRTUAL_AGENTS_CONFIG` | `config/virtual_agents.json` | Path to catalog JSON file |
| `LOG_JSON` | `true` | `false` enables plain-text console lines for discovery logs |

Existing `WEBEX_MEDIA_*` variables unchanged. Catalog feature requires `WEBEX_MEDIA_ENABLED=true`.
