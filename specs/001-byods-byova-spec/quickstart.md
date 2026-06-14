# Quickstart: Validate BYODS CRUD & BYOVA Media Platform

**Feature**: `001-byods-byova-spec` | **Branch**: `001-byods-byova-spec`

Runnable scenarios per user story. BYODS CRUD uses **SDK scripts only**—no REST API. See [sdk-operations.md](./contracts/sdk-operations.md) for method mapping.

---

## Prerequisites

1. Python 3.11+, virtualenv, `pip install -r requirements.txt`
2. Webex Integration + Service App with BYODS scopes (see [README.md](../../README.md))
3. `.env` from [`.env.example`](../../.env.example) including `WEBEX_MEDIA_*` for gRPC media
4. Integration refresh token from `python scripts/register_webhooks.py`
5. Customer org with Service App **authorized** in Control Hub

---

## Scenario 1 — Service App Lifecycle (P1)

**Proves**: User Story 1, FR-001, FR-002, FR-003, SC-001, SC-007

1. Start server: `uvicorn main:app --host 0.0.0.0 --port 8000`
2. Health check: `curl -s http://localhost:8000/health` → `{"status":"ok"}`
3. Authorize Service App in Control Hub
4. Logs: `serviceApp authorized: org_id=...` and optional data source registration
5. Deauthorize → logs: `serviceApp deauthorized: org_id=...`

Invalid payload:

```bash
curl -s -X POST http://localhost:8000/webhooks/webex \
  -H "Content-Type: application/json" \
  -d '{"resource":"unknown"}'
```

**Expected**: HTTP 400, no credential change.

---

## Scenario 2 — BYODS Data Source CRUD via SDK (P2)

**Proves**: User Story 2, FR-004–FR-009, SC-002, SC-004

**Prerequisite**: Org authorized (Scenario 1). Set `ORG_ID` from logs.

### List

```bash
python scripts/manage_datasources.py list --org-id "$ORG_ID"
```

**Expected**: JSON list including auto-registered data source (if enabled).

### Create

```bash
python scripts/manage_datasources.py create --org-id "$ORG_ID" \
  --url "https://your-media-host.example.com/grpc"
```

**Expected**: Created data source with `id`, `status`, `url`. Uses env defaults for schema, audience, subject.

### Get, update, delete

```bash
python scripts/manage_datasources.py get --org-id "$ORG_ID" --id "$DS_ID"

python scripts/manage_datasources.py update --org-id "$ORG_ID" --id "$DS_ID" \
  --token-lifetime-minutes 720

python scripts/manage_datasources.py delete --org-id "$ORG_ID" --id "$DS_ID"
```

### Duplicate URL guard

Repeat `create` with the same `--url`.

**Expected**: Exit code 2, "URL already registered".

### Unauthorized org

```bash
python scripts/manage_datasources.py list \
  --org-id "00000000-0000-0000-0000-000000000000"
```

**Expected**: Exit 1, clear error; no other org data exposed.

### Schema discovery

```bash
python scripts/manage_datasources.py schemas list --org-id "$ORG_ID"
```

---

## Scenario 3 — BYOVA Media Session via SDK (P3)

**Proves**: User Story 3, FR-010–FR-012, SC-003, SC-004

**Prerequisites**:
- `webex-byova[media]>=0.2.0` installed
- `WEBEX_MEDIA_PORT=50051` reachable publicly (VPS/Docker—not Render HTTP-only)
- Data source URL matches gRPC endpoint (`manage_datasources.py get --org-id "$ORG_ID" --id "$DS_ID"`)

### Start server (HTTP + SDK media)

```bash
export WEBEX_MEDIA_PORT=50051
export WEBEX_MEDIA_VERIFY_TOKENS=true
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Expected logs**: `BYOVA media server listening on 0.0.0.0:50051`

### Verify gRPC is up

```bash
grpcurl -plaintext localhost:50051 list
```

**Expected**: `com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent`

### Place WxCC test call

1. Confirm data source `url` matches public host:port/path
2. Route test call through BYOVA-configured WxCC flow
3. Inspect logs for SDK handler events:
   - `session_start` with `conversation_id`
   - `audio_input` activity
   - `session_end` with reason

**Expected**: Inbound audio within 5 seconds of session start (SC-003).

---

## Scenario 4 — Production Operations (P4)

**Proves**: User Story 4, FR-014–FR-016, SC-005, SC-006, SC-008

```bash
curl -s http://localhost:8000/health
curl -s http://localhost:8000/ready
```

Run webhook + SDK CRUD script; confirm structured logs with org_id, operation, outcome—no secrets.

Docker (when added):

```bash
docker compose up --build
curl -s http://localhost:8000/health
```

---

## Scenario 5 — Restart resilience

1. Authorize org (Scenario 1)
2. Restart server
3. Re-run `manage_datasources.py list --org-id "$ORG_ID"` (script re-fetches org tokens via SDK)

**Expected**: CRUD works after Integration refresh + `afetch_token_for_org` without Control Hub re-authorization.

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Webhook 503 | `WEBEX_INTEGRATION_REFRESH_TOKEN` valid |
| Script org error | Org authorized in Control Hub; correct `ORG_ID` |
| `afetch_token_for_org` fails | Service App scopes; Integration token valid |
| Media won't connect | `WEBEX_MEDIA_PORT` public? Data source URL matches gRPC host? |
| grpcurl fails | Install `webex-byova[media]`; check port not in use |

---

## References

- [contracts/sdk-operations.md](./contracts/sdk-operations.md)
- [contracts/openapi.yaml](./contracts/openapi.yaml) — webhook + health only
- [research.md](./research.md)
