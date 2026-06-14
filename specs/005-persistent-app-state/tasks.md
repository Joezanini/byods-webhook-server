# Tasks: Persistent Application State

**Input**: Design documents from `/specs/005-persistent-app-state/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Not explicitly requested in spec. Validation tasks reference `quickstart.md` scenarios (manual restart, CLI, grpcurl). Plan-listed unit/integration tests are optional follow-up—not blocking MVP delivery.

**Organization**: Tasks grouped by user story. Shared persistence layer in `src/persistence/`; CDK changes in `infra/stack.py`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story label (US1–US3)

## Path Conventions

Application code at repository root: `src/`, `scripts/`, `tests/`, `infra/`, `config/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies and local dev tooling for DynamoDB persistence

- [x] T001 Add `boto3`, `aioboto3`, and `cryptography` to `requirements.txt`
- [x] T002 [P] Add persistence environment variables (`PERSISTENCE_BACKEND`, `DYNAMODB_TABLE_NAME`, `PERSISTENCE_ENCRYPTION_KEY`, `PERSISTENCE_AUDIT_TTL_DAYS`, `AWS_ENDPOINT_URL`) to `.env.example`
- [x] T003 [P] Add optional `dynamodb-local` service on port 8001 to `docker-compose.yml` with documented table-create command in comments

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Persistence settings, encryption, DynamoDB client, factory, and production table—I/O layer MUST exist before user story wiring

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 Extend `src/config/settings.py` with persistence settings fields and env loaders per `data-model.md`
- [x] T005 [P] Create `src/persistence/__init__.py` and `src/persistence/client.py` with shared async DynamoDB table handle (aioboto3, honors `AWS_ENDPOINT_URL`)
- [x] T006 [P] Create `src/persistence/encryption.py` with Fernet encrypt/decrypt helpers and `ciphertext_version` support per `contracts/persistence-storage.md`
- [x] T007 Create `src/persistence/factory.py` with `create_token_storage(settings)` returning `memory` or `dynamodb` backend per `PERSISTENCE_BACKEND`
- [x] T008 [P] Add `byods-app-state` DynamoDB table (pay-per-request, SSE enabled, TTL attribute `expires_at`) to `infra/stack.py` per `data-model.md`
- [x] T009 Grant ECS task role DynamoDB read/write on app-state table, inject `DYNAMODB_TABLE_NAME` and `PERSISTENCE_BACKEND=dynamodb` env vars, add `PERSISTENCE_ENCRYPTION_KEY` Secrets Manager field, and output `AppStateTableName` in `infra/stack.py`

**Checkpoint**: Persistence foundation ready—user story implementation can begin

---

## Phase 3: User Story 1 - Durable Org Authorization State (Priority: P1) 🎯 MVP

**Goal**: Org-scoped service app credentials and authorization metadata survive server restarts; deauthorization removes persisted credentials within one webhook cycle

**Independent Test**: Authorize test org via webhook, restart server, run `scripts/manage_datasources.py list --org-id $ORG_ID` without re-auth; deauthorize and confirm BYODS fails—quickstart sections 3 and 6 (SC-001, SC-003, SC-004)

### Implementation for User Story 1

- [x] T010 [P] [US1] Create `src/persistence/org_repository.py` for `ORG#{org_id}` / `PROFILE` upsert and authorization state transitions per `data-model.md`
- [x] T011 [US1] Implement `DynamoDBTokenStorage` in `src/persistence/token_storage.py` satisfying SDK `TokenStorage` protocol (service app tokens to DynamoDB encrypted; integration tokens in-memory only) per `contracts/persistence-storage.md`
- [x] T012 [US1] Refactor `main.py` lifespan to construct `BYOVA(..., token_storage=create_token_storage(settings))` instead of `BYOVA.from_env()` while preserving integration `arefresh` bootstrap
- [x] T013 [US1] Extend `GET /ready` in `main.py` to verify DynamoDB reachability when `PERSISTENCE_BACKEND=dynamodb` (503 when table unreachable)
- [x] T014 [US1] Remove partial access-token logging from `src/webhooks/routes.py`; retain org_id, event, and outcome structured logs (SC-006)
- [x] T015 [US1] Validate P1 scenarios per `specs/005-persistent-app-state/quickstart.md` sections 3 and 6

**Checkpoint**: User Story 1 complete—authorized orgs usable after restart; strict org isolation; deauth clears credentials

---

## Phase 4: User Story 2 - Managed Virtual Agent Catalog (Priority: P2)

**Goal**: Virtual agent catalog stored in DynamoDB; operators manage via CLI; Flow Designer discovery reflects updates without file edit or redeploy

**Independent Test**: Run `scripts/manage_virtual_agents.py update --id 1 --name "Updated Name"`, call `scripts/list_virtual_agents.py` or grpcurl without server restart—quickstart section 4 (SC-002, SC-005)

### Implementation for User Story 2

- [x] T016 [P] [US2] Create `src/persistence/catalog_repository.py` with `list_agents`, `save_agent`, `remove_agent`, aggregate validation, and `ensure_seeded(path)` per `data-model.md`
- [x] T017 [US2] Refactor `src/byova/catalog.py` to export shared validation helpers reused by `catalog_repository.py` and CLI (unique ids, one default, ≥1 agent)
- [x] T018 [US2] Update `src/byova/server.py` to call `catalog_repository.ensure_seeded()` and load entries into `MediaServerConfig.virtual_agents` at startup
- [x] T019 [US2] Update `src/byova/handlers.py` to read-through catalog from `CatalogRepository` on each `list_virtual_agents` event for multi-instance consistency
- [x] T020 [P] [US2] Create `scripts/manage_virtual_agents.py` with list/add/update/remove/set-default commands per `contracts/catalog-management.md`
- [x] T021 [US2] Validate P2 scenarios per `specs/005-persistent-app-state/quickstart.md` section 4

**Checkpoint**: User Stories 1 and 2 complete—durable org tokens and catalog; discovery updates without config file redeploy

---

## Phase 5: User Story 3 - Operational Audit of Service App Lifecycle (Priority: P3)

**Goal**: Queryable recent webhook lifecycle events (org, event type, timestamp, outcome) with TTL retention; no secrets in audit records

**Independent Test**: Trigger authorize/deauthorize webhooks, run `scripts/audit_webhooks.py list --org-id $ORG_ID`—quickstart section 5

### Implementation for User Story 3

- [x] T022 [P] [US3] Create `src/persistence/audit_repository.py` with `record_event` and `list_events` (sanitized detail, TTL `expires_at`) per `contracts/audit-events.md`
- [x] T023 [US3] Append non-blocking audit writes in `src/webhooks/routes.py` on success and handled failure paths using `audit_repository.record_event`
- [x] T024 [P] [US3] Create `scripts/audit_webhooks.py` with `list --org-id --limit --since` per `contracts/audit-events.md`
- [x] T025 [US3] Validate P3 scenarios per `specs/005-persistent-app-state/quickstart.md` section 5

**Checkpoint**: All user stories complete—audit trail available for troubleshooting without affecting call flow

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, production migration guidance, and full success-criteria validation

- [x] T026 [P] Add persistence setup section (encryption key generation, DynamoDB Local, env vars) to `README.md`
- [x] T027 [P] Add persistence section to `infra/AWS_DEPLOYMENT.md` covering table outputs, IAM, Secrets Manager key, and one-time re-auth note for existing authorized orgs
- [x] T028 Run full success criteria checklist (SC-001 through SC-006) per `specs/005-persistent-app-state/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies—start immediately
- **Foundational (Phase 2)**: Depends on Phase 1—**BLOCKS all user stories**
- **User Story 1 (Phase 3)**: Depends on Phase 2—MVP; no dependency on US2/US3
- **User Story 2 (Phase 4)**: Depends on Phase 2; uses shared `src/persistence/client.py` but independent of US1 token items (catalog partition only)
- **User Story 3 (Phase 5)**: Depends on Phase 2; hooks into `src/webhooks/routes.py` (coordinate with US1 if same file—sequential T014 before T023)
- **Polish (Phase 6)**: Depends on desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Foundational only—delivers MVP persistence for org credentials
- **User Story 2 (P2)**: Foundational only—independent catalog partition; can parallel US1 after Phase 2 except shared `handlers.py`/`server.py` touch BYOVA (recommend US1 first if single developer)
- **User Story 3 (P3)**: Foundational + US1 webhook route changes (T014) should land before T023 audit hooks

### Within Each User Story

- Repositories before wiring (`org_repository` → `token_storage` → `main.py`)
- `catalog_repository` before `server.py` / `handlers.py` / CLI
- `audit_repository` before webhook audit writes and CLI

### Parallel Opportunities

- Phase 1: T002 ∥ T003
- Phase 2: T005 ∥ T006 ∥ T008 (after T004); T009 after T008
- US1: T010 parallel with nothing blocking except Phase 2; T011 depends on T010
- US2: T016 ∥ T020 (after Phase 2); T017 before T016 validation reuse
- US3: T022 ∥ T024 (after Phase 2)
- Polish: T026 ∥ T027

---

## Parallel Example: User Story 1

```bash
# After Phase 2 completes, start repository and infra validation in parallel:
Task T010: "Create src/persistence/org_repository.py"
Task T008: "Add DynamoDB table to infra/stack.py"  # if not done in Phase 2

# Sequential core path:
Task T011: "Implement DynamoDBTokenStorage in src/persistence/token_storage.py"
Task T012: "Refactor main.py lifespan for custom token_storage"
Task T013: "Extend GET /ready with DynamoDB check"
Task T014: "Redact token logging in src/webhooks/routes.py"
```

---

## Parallel Example: User Story 2

```bash
# Parallel after Phase 2:
Task T016: "Create src/persistence/catalog_repository.py"
Task T020: "Create scripts/manage_virtual_agents.py"

# Then wire BYOVA:
Task T017 → T018 → T019
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (**CRITICAL**)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: quickstart sections 3 and 6
5. Deploy CDK table + update Secrets Manager encryption key before ECS rollout

### Incremental Delivery

1. Setup + Foundational → persistence layer ready
2. User Story 1 → validate restart + BYODS → **MVP**
3. User Story 2 → validate catalog CLI + discovery → deploy
4. User Story 3 → validate audit CLI → deploy
5. Polish → documentation + full SC checklist

### Parallel Team Strategy

1. Team completes Setup + Foundational together
2. After Phase 2:
   - Developer A: User Story 1 (token storage + main.py)
   - Developer B: User Story 2 (catalog repository + CLI)—coordinate on `handlers.py` merge
   - Developer C: User Story 3 (audit)—after US1 T014 lands
3. Polish together

---

## Notes

- SDK `TokenStorage` protocol is in `webex_byova.auth.storage`—do not reimplement webhook token exchange logic
- Integration OAuth tokens MUST NOT be written to DynamoDB (FR-008)
- `config/virtual_agents.json` is bootstrap seed only after US2; file edits alone no longer update runtime catalog
- Existing production orgs need one-time re-authorization or webhook replay after deploy—document in T027
- `[P]` tasks = different files; `src/webhooks/routes.py` is shared by US1 (T014) and US3 (T023)—serialize those edits
