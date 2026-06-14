# Quickstart: Virtual Agent Catalog for Flow Designer

**Feature**: `002-virtual-agent-catalog`

Validates agent discovery, **console logging when Flow Designer (or grpcurl) requests the list**, and session agent context. Requires feature `001` prerequisites (authorized org, registered data source, media server running).

---

## Prerequisites

1. Feature `001` quickstart complete: Integration tokens, authorized org, data source URL pointing at gRPC endpoint.
2. `webex-byova[media]>=0.3.0` installed (catalog + `list_virtual_agents` event).
3. `WEBEX_MEDIA_ENABLED=true`.
4. Sample catalog present at `config/virtual_agents.json` (six Cisco demo agents).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Fill Webex credentials
```

---

## Scenario 1: Startup catalog load

**Goal**: Confirm catalog loads and media server starts with six agents.

```bash
export LOG_JSON=false   # plain console lines for this scenario
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Expected console output** (representative):

```text
BYOVA media server listening on 0.0.0.0:50051
Virtual agent catalog loaded: 6 agents from config/virtual_agents.json
```

**Failure examples** (startup abort):
- `Duplicate virtual_agent_id: 1`
- `Multiple default agents configured`
- `Catalog file not found: config/virtual_agents.json`

---

## Scenario 2: ListVirtualAgents via grpcurl (simulates Flow Designer)

**Goal**: Prove discovery response and **INFO-level console log** on list request.

With server running (`LOG_JSON=false`):

```bash
grpcurl -plaintext \
  -H 'trackingid: quickstart-test-001' \
  localhost:50051 \
  com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents
```

**Expected grpcurl response**:

```json
{
  "virtualAgents": [
    { "virtualAgentId": "1", "virtualAgentName": "Travel Booking Agent" },
    { "virtualAgentId": "2", "virtualAgentName": "Credit card service" }
  ]
}
```

(All six agents present; `isDefault` only on entries configured as default.)

**Expected server console line** (INFO):

```text
Flow Designer requested virtual agent list — org=n/a agents=6 tracking_id=quickstart-test-001
```

With `LOG_JSON=true` (default), the same event appears as one JSON line with `"operation": "list_virtual_agents"` and `"agent_count": 6`.

**Pass criteria**:
- Response contains 6 agents (SC-002)
- Exactly one INFO log line per grpcurl invocation
- `tracking_id` appears in log when metadata header sent

---

## Scenario 3: Flow Designer integration (manual)

**Goal**: End-to-end validation in WxCC UI.

1. Control Hub → ensure BYOVA data source is **ACTIVE** and URL matches public gRPC endpoint.
2. Flow Designer → open IVR flow → add/configure **Virtual Agent** activity.
3. Select your BYOVA provider connector.
4. Open the virtual agent picker.

**Expected**:
- Six named agents appear (not an empty list).
- Server console shows `list_virtual_agents` INFO log when the picker loads (may include `customer_org_id` from WxCC).

**Troubleshooting**:
- Empty picker + no log line → Flow Designer not reaching your gRPC port (firewall, wrong data source URL, media disabled).
- Empty picker + log line with `agents=0` → catalog not wired into SDK config; check `webex-byova` version.
- Log line but picker error → token verification; try `WEBEX_MEDIA_VERIFY_TOKENS=false` locally only.

---

## Scenario 4: Custom catalog without code changes

**Goal**: Validate FR-007 / SC-003.

1. Edit `config/virtual_agents.json` — rename "Travel Booking Agent" to "Demo Travel Bot".
2. Restart server.
3. Re-run Scenario 2 grpcurl or refresh Flow Designer picker.

**Expected**: Response and logs reflect new name; agent count unchanged.

---

## Scenario 5: Session agent identifier (P3)

**Goal**: Confirm `virtual_agent_id` logged at session start.

Place a test call through a flow configured with agent id `1` (Travel Booking Agent), or use WxCC test harness if available.

**Expected console** (INFO on `session_start`):

```text
Media session started — conversation_id=<uuid> virtual_agent_id=1 customer_org_id=<org>
```

If flow uses an unknown agent id `99`:

**Expected** (WARNING):

```text
virtual_agent_id=99 not found in catalog — session continues with catalog_match=false
```

---

## Scenario 6: Invalid catalog fail-fast

```bash
# Temporarily break catalog (duplicate ids), then start server
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Expected**: Process exits before binding port 50051; stderr explains duplicate ID. No silent empty list.

---

## Environment reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `WEBEX_VIRTUAL_AGENTS_CONFIG` | `config/virtual_agents.json` | Catalog file path |
| `LOG_JSON` | `true` | `false` for human-readable discovery lines |
| `WEBEX_MEDIA_ENABLED` | `true` | Must be true for discovery |
| `WEBEX_MEDIA_PORT` | `50051` | gRPC bind port |

See [contracts/virtual-agent-catalog.md](./contracts/virtual-agent-catalog.md) and [data-model.md](./data-model.md) for field-level detail.
