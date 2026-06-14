# Contract: Service App Lifecycle Audit (P3)

**Feature**: `005-persistent-app-state` | Priority P3 (optional)

Append-only audit trail for webhook troubleshooting. Not on critical path for BYODS/BYOVA call flow.

---

## Write contract

**Trigger**: End of `POST /webhooks/webex` handler in `src/webhooks/routes.py` (success and handled failure paths).

**Function**: `audit_repository.record_event(...)`

| Field | Source |
|-------|--------|
| `org_id` | Webhook result or payload when available; `unknown` on pre-parse failures |
| `event_type` | `authorized` \| `deauthorized` \| `processing_failure` |
| `outcome` | `success` \| `failure` |
| `timestamp` | UTC now |
| `request_id` | FastAPI request state |
| `detail` | Sanitized exception message (max 500 chars); no token substrings |
| `expires_at` | now + `PERSISTENCE_AUDIT_TTL_DAYS` |

**Failure policy**: Audit write failure logs ERROR but does **not** fail webhook HTTP response (observability-only).

---

## Read contract

**Script**: `scripts/audit_webhooks.py`

```
audit_webhooks.py list [--org-id ORG] [--limit N] [--since ISO8601]
```

**Output** (stdout, JSON lines or table):

```json
{
  "org_id": "abc-123",
  "event_type": "authorized",
  "outcome": "success",
  "timestamp": "2026-06-13T12:00:00Z",
  "request_id": "req-xyz",
  "detail": null
}
```

**Query**: `Query` on `PK=ORG#{org_id}`, `SK begins_with AUDIT#`, descending, limit N.

---

## Security

- MUST NOT persist or print `access_token`, `refresh_token`, or `Authorization` header values
- `detail` MUST pass through sanitizer stripping token-like patterns before write

---

## DynamoDB TTL

Table attribute `expires_at` (Number, epoch seconds) enables automatic deletion. Core org/catalog items do not use TTL.
