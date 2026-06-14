# Implementation Plan: Persistent Application State

**Branch**: `005-persistent-app-state` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-persistent-app-state/spec.md`  
**User preference**: Amazon DynamoDB free tier where possible.

## Summary

Add DynamoDB-backed persistence so authorized org credentials and the virtual agent catalog survive restarts and multi-instance ECS deployments. Implement `DynamoDBTokenStorage` against the SDK's documented `TokenStorage` protocol (service app tokens only; integration tokens stay in-memory from env/secrets). Move catalog source of truth from `config/virtual_agents.json` to DynamoDB with CLI management and read-through on `ListVirtualAgents`. Optional P3 lifecycle audit with DynamoDB TTL. Extend CDK stack with one on-demand table and ECS IAM/env wiring. Webhook HTTP contract unchanged.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastAPI, uvicorn, `webex-byova[media]>=0.2.0`, `boto3` + `aioboto3`, `cryptography` (Fernet), python-dotenv, pytest, moto or DynamoDB Local (testing)

**Storage**: Amazon DynamoDB single table `byods-app-state` (on-demand billing); DynamoDB Local for dev; `PERSISTENCE_BACKEND=memory` for unit tests

**Testing**: pytest unit tests for repositories, encryption, catalog validation; integration tests for token round-trip, webhook persistence, catalog seed; manual quickstart scenarios

**Target Platform**: Linux — local Docker, AWS ECS Fargate (existing `infra/stack.py`)

**Project Type**: FastAPI HTTP + in-process SDK gRPC media server (extends features 001–002)

**Performance Goals**: DynamoDB p99 <50ms for single-item reads; catalog discovery unchanged (<500ms p99 for ListVirtualAgents); webhook handling adds ≤20ms persistence overhead

**Constraints**: SDK-first token paths; no integration secrets in DynamoDB; webhook flow preserved; free-tier-friendly single table with low QPS; eventual catalog consistency acceptable v1

**Scale/Scope**: Tens of customer orgs; ≤20 catalog agents; single ECS service (1–N tasks sharing table); 30-day audit retention

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verify against `.specify/memory/constitution.md`:

- [x] **SDK-First**: Custom storage implements SDK `TokenStorage` protocol; webhooks still use `ahandle_service_app_webhook`; BYODS/BYOVA unchanged at API boundary.
- [x] **Webhook Integrity**: `POST /webhooks/webex` request/response preserved; persistence hooks inside existing handler + token storage callbacks only.
- [x] **Modular Architecture**: New `src/persistence/` common layer; webhook module uses token storage; BYOVA uses `CatalogRepository`; no cross-leakage.
- [x] **Production Reliability**: `/ready` checks DynamoDB; structured logging maintained; env-driven config; Docker + CDK updates; audit failures non-blocking.
- [x] **Security by Default**: Fernet encryption for org tokens; integration secrets in Secrets Manager only; audit sanitizer; org-scoped keys; redact token logging in webhook route.
- [x] **Incremental Delivery**: P1 token storage → P2 catalog → P3 audit → CDK/infra → tests/quickstart.

**Post-Phase 1 re-check**: All gates pass. DynamoDB adds infrastructure complexity justified by multi-org production requirement; SDK protocol avoids custom Webex persistence logic.

## Project Structure

### Documentation (this feature)

```text
specs/005-persistent-app-state/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── persistence-storage.md
│   ├── catalog-management.md
│   └── audit-events.md
└── tasks.md                    # Phase 2 (/speckit-tasks)
```

### Source Code (repository root — additions/changes)

```text
byods-webhook-server/
├── main.py                           # MODIFY: wire DynamoDBTokenStorage into BYOVA; readiness check
├── requirements.txt                  # + boto3, aioboto3, cryptography
├── docker-compose.yml                # MODIFY: optional dynamodb-local service
├── .env.example                      # + PERSISTENCE_* , DYNAMODB_*, AWS_ENDPOINT_URL
├── config/virtual_agents.json        # KEEP: bootstrap seed only
├── src/
│   ├── config/settings.py            # MODIFY: persistence settings
│   ├── persistence/                  # NEW
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── encryption.py
│   │   ├── token_storage.py          # DynamoDBTokenStorage
│   │   ├── org_repository.py
│   │   ├── catalog_repository.py
│   │   ├── audit_repository.py
│   │   └── factory.py
│   ├── webhooks/routes.py            # MODIFY: audit writes; redact token log line
│   └── byova/
│       ├── catalog.py                # MODIFY: extract shared validation; repo-backed load
│       ├── server.py                 # MODIFY: seed + load from CatalogRepository
│       └── handlers.py               # MODIFY: read-through catalog on list_virtual_agents
├── scripts/
│   ├── manage_virtual_agents.py      # NEW: catalog CLI
│   └── audit_webhooks.py             # NEW: P3 audit CLI
├── tests/
│   ├── unit/
│   │   ├── test_token_storage.py
│   │   ├── test_catalog_repository.py
│   │   └── test_encryption.py
│   └── integration/
│       ├── test_persistence_webhook.py
│       └── test_catalog_persistence.py
└── infra/
    ├── stack.py                      # MODIFY: DynamoDB table, IAM, env, secret field
    └── AWS_DEPLOYMENT.md             # MODIFY: persistence section
```

**Structure Decision**: New `src/persistence/` as shared layer per constitution common-layer guidance. Webhook and BYOVA modules depend on narrow repository interfaces, not raw boto3.

## Complexity Tracking

> No constitution violations requiring justification.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Phase 0: Research Summary

See [research.md](./research.md):

| Topic | Decision |
|-------|----------|
| Durable store | DynamoDB single table, on-demand |
| Org tokens | SDK `TokenStorage` implementation; encrypted CREDS items |
| Integration tokens | In-memory only (FR-008) |
| Token encryption | Fernet + `PERSISTENCE_ENCRYPTION_KEY` in Secrets Manager |
| Catalog | DynamoDB source of truth; CLI management; read-through discovery |
| Catalog migration | Seed from JSON when table empty |
| Audit | DynamoDB items with TTL; CLI retrieval |
| Local dev | DynamoDB Local in Docker |
| Readiness | Fail 503 if DynamoDB required but unavailable |

## Phase 1: Design Summary

See [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md).

### DynamoDB table design

Single table `byods-app-state`:

| PK | SK | Purpose |
|----|-----|---------|
| `ORG#{org_id}` | `PROFILE` | Authorization metadata |
| `ORG#{org_id}` | `CREDS` | Encrypted service app tokens |
| `ORG#{org_id}` | `AUDIT#{ts}#{uuid}` | Lifecycle audit (TTL) |
| `CATALOG` | `AGENT#{id}` | Virtual agent entry |
| `CATALOG` | `META` | Catalog version/count |

### Application wiring

1. **Startup**: `create_token_storage(settings)` → pass to `BYOVA(..., token_storage=storage)`; integration refresh from env unchanged.
2. **Webhook**: SDK persists tokens via storage protocol; route handler appends audit record.
3. **Catalog**: `ensure_seeded()` on startup; `list_virtual_agents` handler refreshes from repository.
4. **Ready probe**: DynamoDB health + integration bootstrap.

### CDK changes (`infra/stack.py`)

- `aws_dynamodb.Table` — pay-per-request, SSE enabled, TTL on `expires_at`
- Grant task role read/write on table
- Env: `DYNAMODB_TABLE_NAME`, `PERSISTENCE_BACKEND=dynamodb`
- Secret field: `PERSISTENCE_ENCRYPTION_KEY`
- Output: `AppStateTableName`

### Delivery order (for `/speckit-tasks`)

1. **Foundation**: settings, encryption, DynamoDB client, table CDK, `.env.example`
2. **P1**: `DynamoDBTokenStorage`, org profile, main.py wiring, readiness, webhook redaction
3. **P2**: `CatalogRepository`, validation reuse, seed migration, CLI, read-through discovery
4. **P3**: `AuditRepository`, webhook audit writes, audit CLI
5. **Quality**: unit/integration tests, quickstart validation, README/AWS_DEPLOYMENT updates

### Dependencies

- Feature 001 webhook + SDK token model (baseline)
- Feature 002 catalog validation semantics (unchanged rules)
- Feature 004 CDK/ECS deployment (table added to existing stack, not pipeline metadata storage)

### Risks and mitigations

| Risk | Mitigation |
|------|------------|
| SDK catalog not hot-swappable | Read-through in `list_virtual_agents` handler updates response list directly |
| Existing prod orgs lose tokens on deploy | Document one-time re-auth OR run migration from live webhook replay; seed does not fabricate tokens |
| DynamoDB Local drift from AWS | Integration tests against moto; quickstart uses Local |
| Encryption key rotation | `ciphertext_version` field; document re-auth fallback for v1 |

## Phase 2 Preview

`/speckit-tasks` will generate dependency-ordered tasks from this plan. No `tasks.md` created by this command.
