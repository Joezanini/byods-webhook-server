# Quickstart: Persistent Application State

**Feature**: `005-persistent-app-state` | **Branch**: `005-persistent-app-state`

Validation scenarios for durable org authorization, catalog management, and audit. See [data-model.md](./data-model.md) and [contracts/](./contracts/) for schemas.

---

## Prerequisites

- Python 3.11+ venv with `pip install -r requirements.txt`
- Webex Integration + Service App credentials in `.env` (unchanged from feature 001)
- Docker (for DynamoDB Local) OR AWS credentials with DynamoDB table deployed via CDK
- `PERSISTENCE_ENCRYPTION_KEY` — generate once:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add to `.env`:

```bash
PERSISTENCE_BACKEND=dynamodb
DYNAMODB_TABLE_NAME=byods-app-state
PERSISTENCE_ENCRYPTION_KEY=<generated-key>
AWS_ENDPOINT_URL=http://localhost:8001   # DynamoDB Local only
AWS_REGION=us-east-1
```

---

## 1. Start DynamoDB Local

```bash
docker run -d --name dynamodb-local -p 8001:8000 amazon/dynamodb-local
```

Create table (after CDK deploy, or manual for local):

```bash
aws dynamodb create-table \
  --endpoint-url http://localhost:8001 \
  --table-name byods-app-state \
  --attribute-definitions AttributeName=PK,AttributeType=S AttributeName=SK,AttributeType=S \
  --key-schema AttributeName=PK,KeyType=HASH AttributeName=SK,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

Enable TTL on `expires_at` (audit):

```bash
aws dynamodb update-time-to-live \
  --endpoint-url http://localhost:8001 \
  --table-name byods-app-state \
  --time-to-live-specification "Enabled=true, AttributeName=expires_at" \
  --region us-east-1
```

---

## 2. Start server and verify readiness

```bash
export WEBEX_INTEGRATION_REFRESH_TOKEN=...
uvicorn main:app --host 0.0.0.0 --port 8000
```

```bash
curl -s http://localhost:8000/health    # expect {"status":"ok"}
curl -s http://localhost:8000/ready     # expect {"status":"ok"} when DynamoDB + integration ready
```

On first start, catalog seeds from `config/virtual_agents.json` if table empty (check logs for `catalog seeded`).

---

## 3. P1 — Durable org authorization (SC-001, SC-004)

1. Authorize a test org via Control Hub (or replay a valid `authorized` webhook to `POST /webhooks/webex`).
2. Confirm BYODS read works:

```bash
python scripts/manage_datasources.py list --org-id "$ORG_ID"
```

3. **Restart** the server process (simulate cold start).
4. Re-run step 2 **without** a new Control Hub authorization — expect success (SC-001).
5. Deauthorize org in Control Hub; confirm webhook processed.
6. Re-run step 2 — expect authorization failure (SC-004).
7. Inspect DynamoDB: `CREDS` item absent for org; `PROFILE.authorization_state=deauthorized`.

```bash
aws dynamodb get-item \
  --endpoint-url http://localhost:8001 \
  --table-name byods-app-state \
  --key '{"PK":{"S":"ORG#'"$ORG_ID"'"},"SK":{"S":"PROFILE"}}' \
  --region us-east-1
```

---

## 4. P2 — Catalog update without redeploy (SC-002, SC-005)

List catalog:

```bash
python scripts/manage_virtual_agents.py list
```

Update display name:

```bash
python scripts/manage_virtual_agents.py update --id 1 --name "Updated Travel Agent"
```

Verify discovery (no server restart):

```bash
python scripts/list_virtual_agents.py --org-id "$ORG_ID"
# or grpcurl -plaintext localhost:50051 \
#   com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents
```

Expect updated name in response (SC-002).

Validation negative test:

```bash
python scripts/manage_virtual_agents.py remove --id 1
# ... repeat for all agents until one remains ...
python scripts/manage_virtual_agents.py remove --id <last-id>
# expect exit 1 + EMPTY_CATALOG error (SC-005)
```

---

## 5. P3 — Audit trail (optional)

After authorize/deauthorize webhooks:

```bash
python scripts/audit_webhooks.py list --org-id "$ORG_ID" --limit 10
```

Confirm events show `event_type`, `timestamp`, `outcome`; no token fields (SC-006).

---

## 6. Multi-org isolation (SC-003)

With two authorized test orgs (A and B):

```bash
python scripts/manage_datasources.py list --org-id "$ORG_A"
python scripts/manage_datasources.py list --org-id "$ORG_B"
```

Verify org A operations never log or return org B credentials. DynamoDB `get-item` for `ORG#A/CREDS` returns only org A data.

---

## 7. AWS production (ECS)

After CDK deploy with DynamoDB table:

1. Add `PERSISTENCE_ENCRYPTION_KEY` to Secrets Manager `byods-webhook-server/webex`.
2. Confirm ECS task env includes `DYNAMODB_TABLE_NAME` and task role has DynamoDB permissions.
3. Force new deployment; repeat sections 3–4 against production URLs.

See [infra/AWS_DEPLOYMENT.md](../../infra/AWS_DEPLOYMENT.md) (updated during implementation) for table outputs and IAM notes.

---

## Success criteria checklist

| ID | Scenario | Pass condition |
|----|----------|----------------|
| SC-001 | Restart + BYODS read | All prior authorized orgs work without re-auth |
| SC-002 | Catalog rename | Flow Designer/grpcurl shows new name without file edit/redeploy |
| SC-003 | Multi-org | No cross-org credential exposure |
| SC-004 | Deauth | Credentials gone within one webhook cycle |
| SC-005 | Invalid catalog | CLI rejects empty/duplicate/multi-default |
| SC-006 | Secret leakage | Audit/logs contain no plaintext tokens |
