# Research: Persistent Application State

**Feature**: `005-persistent-app-state` | **Date**: 2026-06-13

## R1: Durable store selection

**Decision**: Amazon DynamoDB (single-table design, on-demand billing for v1) as the primary durable store for org profiles, org-scoped service app tokens, virtual agent catalog entries, and lifecycle audit events.

**Rationale**:
- User preference for DynamoDB free tier; expected volume (tens of orgs, single-digit catalog size, low webhook QPS) fits within Always Free limits (25 GB storage; low read/write volume).
- Existing production target is AWS ECS Fargate (`infra/stack.py`); colocating state in DynamoDB avoids new network hops or managed DB overhead.
- Native TTL supports P3 audit retention without a sweeper job.

**Alternatives considered**:
- *PostgreSQL/RDS* — rejected for v1; higher ops cost and no free-tier alignment for this workload.
- *S3 JSON files* — rejected; weak concurrent update semantics and no native per-item TTL for audit.
- *Secrets Manager per org* — rejected; ~$0.40/secret/month scales poorly for multi-org; spec allows encryption in a managed database instead.

---

## R2: SDK token persistence (org-scoped only)

**Decision**: Implement `DynamoDBTokenStorage` satisfying the SDK `TokenStorage` protocol (`webex_byova.auth.storage.TokenStorage`). Persist **service app tokens per org** and org authorization metadata. Keep **integration OAuth tokens in-process only** (refreshed from `WEBEX_INTEGRATION_REFRESH_TOKEN` on startup)—never written to DynamoDB (FR-008).

**Rationale**: SDK documents `TokenStorage` for production persistence; `BYOVA.__init__(..., token_storage=...)` accepts a custom implementation. Webhook handling via `ahandle_service_app_webhook` already reads/writes through token storage—no webhook rewrite required.

**Protocol methods**:

| Method | Persistence behavior |
|--------|---------------------|
| `get/set_integration_tokens` | In-memory only (delegate to nested `InMemoryTokenStorage` slice) |
| `get/set/delete_service_app_tokens` | DynamoDB + field encryption |
| `list_registered_orgs` | DynamoDB query on org partition prefix |

**Alternatives considered**:
- *Post-webhook sync layer* — rejected; duplicates SDK writes and risks drift on token refresh inside SDK.
- *Persist integration tokens* — rejected; violates FR-008 and duplicates Secrets Manager/env.

---

## R3: Token protection at rest

**Decision**: Application-level encryption of token fields using Fernet (`cryptography` package) with a 32-byte key supplied via `PERSISTENCE_ENCRYPTION_KEY` (local `.env`) or AWS Secrets Manager field on the existing Webex secret (production). DynamoDB table encryption at rest enabled (AWS-managed keys).

**Rationale**: Meets FR-002 without per-org Secrets Manager cost. Fernet is sufficient for symmetric encryption of small token blobs at rest.

**Alternatives considered**:
- *DynamoDB SSE-KMS only* — insufficient alone; operators with table read access would see plaintext tokens.
- *AWS Encryption SDK* — rejected for v1; heavier dependency for small payloads.

---

## R4: Virtual agent catalog source of truth

**Decision**: Replace file-backed catalog as source of truth with DynamoDB items under partition `CATALOG`. Retain `src/byova/catalog.py` validation logic; add `CatalogRepository` for load/save. **Read-through on each `ListVirtualAgents`** (via existing SDK `list_virtual_agents` handler) so multi-instance deployments see updates without restart; cache optional later if latency requires it.

**Rationale**: Meets FR-009–FR-015 and SC-002; catalog size is tiny (≪10 items); discovery QPS is low. Read-through gives natural eventual consistency for v1.

**Migration**: On empty catalog table at startup, seed from `config/virtual_agents.json` if present (one-time bootstrap for existing deployments).

**Management interface**: CLI `scripts/manage_virtual_agents.py` (mirrors `manage_datasources.py` pattern)—list, add, update, remove, set-default. No new public HTTP admin routes in v1 (security-by-default).

**Alternatives considered**:
- *Keep JSON file as source* — rejected; does not meet multi-instance or no-redeploy update requirements.
- *REST admin API* — deferred; CLI matches existing operator workflows and avoids new attack surface.

---

## R5: Operational audit (P3)

**Decision**: Write audit items to DynamoDB (`PK=ORG#{org_id}`, `SK=AUDIT#{timestamp}#{uuid}`) on webhook success/failure from `src/webhooks/routes.py`. Enable DynamoDB TTL on `expires_at` (default 30 days). Retrieval via `scripts/audit_webhooks.py list --org-id ... --limit N`.

**Rationale**: Queryable recent history without log parsing; TTL handles retention; no secrets in audit payload.

**Alternatives considered**:
- *CloudWatch Logs Insights only* — rejected for P3; spec asks for retrievable audit records.
- *Separate audit table* — rejected for v1; single-table keeps free-tier footprint minimal.

---

## R6: Local development and testing

**Decision**: Add optional `dynamodb-local` service to `docker-compose.yml`. Tests use `InMemoryPersistenceBackend` or moto/local DynamoDB with `PERSISTENCE_BACKEND=dynamodb` and `AWS_ENDPOINT_URL`. Unit tests mock repository interfaces; integration tests cover token round-trip and catalog validation.

**Rationale**: Operators already use Docker locally; DynamoDB Local avoids AWS credentials for dev.

---

## R7: Infrastructure (CDK)

**Decision**: Extend `ByodsWebhookStack` with one DynamoDB table (`byods-app-state`), grant ECS task role `dynamodb:GetItem/PutItem/UpdateItem/DeleteItem/Query`, inject `DYNAMODB_TABLE_NAME` env var, add `PERSISTENCE_ENCRYPTION_KEY` to Secrets Manager. On-demand billing mode.

**Rationale**: Minimal CDK diff; reuses existing task role pattern. Provisioned 1/1 RCU/WCU alternative documented if operator wants stricter free-tier cap.

---

## R8: Readiness and failure modes

**Decision**: Extend `GET /ready` to verify DynamoDB reachability (lightweight `GetItem` on `CATALOG/META` or `DescribeTable`) in addition to integration bootstrap. If DynamoDB unavailable at startup, fail readiness (503)—no silent in-memory fallback in production (`PERSISTENCE_BACKEND=dynamodb`).

**Rationale**: Spec edge case: never silently serve stale or cross-org data when persistence is required.

**Local fallback**: `PERSISTENCE_BACKEND=memory` for unit tests and optional local quickstart without Docker DynamoDB (documented as non-production).

---

## R9: Webhook logging hygiene

**Decision**: When touching webhook routes for audit persistence, remove or redact the existing partial access-token log line in `src/webhooks/routes.py` (logs first 12 chars of token)—aligns with SC-006 and FR-019 without changing webhook HTTP behavior.

**Rationale**: Persistence work is an opportune fix for secret-adjacent logging; not a webhook protocol change.
