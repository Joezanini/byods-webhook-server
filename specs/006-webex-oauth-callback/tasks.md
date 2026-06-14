# Tasks: Webex Integration OAuth Callback

**Input**: Design documents from `/specs/006-webex-oauth-callback/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Depends on**: Feature 005 persistent app state (DynamoDB table, `DynamoDBTokenStorage` for org tokens, encryption, factory)

**Tests**: Not explicitly requested in spec. Plan lists unit/integration tests as optional follow-up. Validation tasks reference `quickstart.md` scenarios.

**Organization**: Tasks grouped by user story. OAuth callback and bootstrap in `src/webhooks/`; integration token persistence extends `src/persistence/token_storage.py`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story label (US1–US3)

## Path Conventions

Application code at repository root: `src/`, `scripts/`, `tests/`, `infra/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Environment and configuration prep for production OAuth callback

- [x] T001 Update `.env.example` with production `WEBEX_INTEGRATION_REDIRECT_URI` example (`/oauth/webex/callback`), note that `WEBEX_INTEGRATION_REFRESH_TOKEN` is optional bootstrap when storage empty per `contracts/oauth-callback.md`
- [x] T002 [P] Confirm feature 005 persistence is enabled locally (`PERSISTENCE_BACKEND=dynamodb`, table reachable) before starting Phase 2 — see `specs/005-persistent-app-state/quickstart.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Settings, integration token serializers, DynamoDB persistence for `INTEGRATION/CREDS`, and bootstrap module skeleton

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Extend `src/config/settings.py` with `integration_redirect_uri` loader and `integration_redirect_path` property (path from `urllib.parse.urlparse(WEBEX_INTEGRATION_REDIRECT_URI)`) per `research.md` R1
- [x] T004 [P] Add `_oauth_tokens_to_payload` / `_payload_to_oauth_tokens` helpers in `src/persistence/token_storage.py` mirroring existing service app token serializers per `contracts/persistence-integration-tokens.md`
- [x] T005 Extend `DynamoDBTokenStorage.get_integration_tokens` and `set_integration_tokens` in `src/persistence/token_storage.py` to read/write encrypted `PK=INTEGRATION`, `SK=CREDS` (remove in-memory-only delegate for integration when backend is dynamodb) per `data-model.md`
- [x] T006 [P] Create `src/webhooks/integration_bootstrap.py` with async `bootstrap_integration(sdk, settings, token_storage) -> bool` skeleton (storage-first precedence, env fallback) and `ensure_service_app_webhooks_if_configured(sdk, settings)` stub per `contracts/oauth-callback.md`

**Checkpoint**: Integration token persistence and bootstrap module ready—user story implementation can begin

---

## Phase 3: User Story 1 - Production OAuth Callback for Integration Authorization (Priority: P1) 🎯 MVP

**Goal**: Production `GET` callback exchanges authorization code via SDK, persists integration tokens to DynamoDB, and startup loads tokens from storage without env refresh token

**Independent Test**: Complete OAuth via production callback URL, verify `INTEGRATION/CREDS` in DynamoDB, restart server without `WEBEX_INTEGRATION_REFRESH_TOKEN`, confirm `/ready` returns 200 — `quickstart.md` sections 3–4 (SC-001, SC-002, SC-004)

### Implementation for User Story 1

- [x] T007 [US1] Create `src/webhooks/oauth_callback.py` with GET handler: extract `code` / OAuth `error` query params, call `sdk.integration.aexchange_code(code)`, then `token_storage.set_integration_tokens(tokens)`; on persistence failure return failure HTML and discard tokens (no in-memory retention) per `spec.md` clarifications and `contracts/oauth-callback.md`
- [x] T008 [US1] Add minimal success/failure `HTMLResponse` helpers in `src/webhooks/oauth_callback.py` (no token values in body) per FR-006
- [x] T009 [US1] Mount OAuth callback router at `settings.integration_redirect_path` from `src/webhooks/routes.py` (skip mount when redirect URI is localhost-only for local script mode) per `research.md` R1
- [x] T010 [US1] Implement storage-first `bootstrap_integration` in `src/webhooks/integration_bootstrap.py`: if `get_integration_tokens()` returns tokens → `arefresh()`; elif env `WEBEX_INTEGRATION_REFRESH_TOKEN` → `arefresh(token)` (persists to storage); else return False per FR-004/FR-004a
- [x] T011 [US1] Refactor `main.py` lifespan to call `bootstrap_integration()` instead of inline env-only refresh; set `app.state.integration_ready` from result; preserve persistence and media startup wiring
- [x] T012 [US1] Validate P1 scenarios per `specs/006-webex-oauth-callback/quickstart.md` sections 3–4

**Checkpoint**: User Story 1 complete—OAuth callback persists tokens; restart works from DynamoDB alone

---

## Phase 4: User Story 2 - Uninterrupted Service App Webhook Monitoring (Priority: P2)

**Goal**: Idempotent webhook verification on startup and after successful OAuth callback using SDK `aensure_service_app_webhooks`

**Independent Test**: Restart server twice with existing webhooks—no duplicates; manual `register_webhooks.py` still works — `quickstart.md` section 5 (SC-007)

### Implementation for User Story 2

- [x] T013 [US2] Implement `ensure_service_app_webhooks_if_configured` in `src/webhooks/integration_bootstrap.py` calling `sdk.webhooks.aensure_service_app_webhooks(settings.webhook_target_url)` when URL configured per FR-009/FR-009a
- [x] T014 [US2] Invoke webhook ensure after successful token persist in `src/webhooks/oauth_callback.py` post-callback path per clarifications session Q4
- [x] T015 [US2] Invoke webhook ensure after successful `bootstrap_integration` in `main.py` lifespan when `integration_ready` and webhook target URL set per FR-009
- [x] T016 [P] [US2] Update `scripts/register_webhooks.py` to document production flow: print `get_authorization_url()` when redirect URI is HTTPS; keep `aensure_service_app_webhooks` for manual re-registration per `research.md` R9 and FR-009b
- [x] T017 [US2] Validate P2 scenarios per `specs/006-webex-oauth-callback/quickstart.md` section 5

**Checkpoint**: User Stories 1 and 2 complete—tokens durable and webhooks verified idempotently

---

## Phase 5: User Story 3 - Secure, Operator-Friendly Callback Experience (Priority: P3)

**Goal**: Clear browser outcomes, no secret leakage in logs, best-effort CSRF state validation

**Independent Test**: Successful and failed callbacks show appropriate HTML; logs contain no tokens or codes — `quickstart.md` section 6 (SC-003)

### Implementation for User Story 3

- [x] T018 [US3] Handle Webex OAuth error redirects (`error`, `error_description`) in `src/webhooks/oauth_callback.py` with actionable failure HTML and no internal config exposure per FR-007
- [x] T019 [US3] Add structured logging in `src/webhooks/oauth_callback.py` with `operation=oauth_callback`, request ID, outcome—never log `code`, access token, or refresh token per FR-011/FR-013
- [x] T020 [US3] Add best-effort `state` query param validation in `src/webhooks/oauth_callback.py` when present (reject mismatch); document accept-without-state for externally initiated flows per FR-012 and spec assumptions
- [x] T021 [US3] Validate P3 scenarios per `specs/006-webex-oauth-callback/quickstart.md` section 6

**Checkpoint**: All user stories complete—secure callback UX and observability

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Tests, documentation, regression validation

- [x] T022 [P] Extend `tests/unit/test_token_storage.py` with integration token DynamoDB round-trip, overwrite on re-auth, and missing-item returns `None` per `contracts/persistence-integration-tokens.md`
- [x] T023 [P] Create `tests/unit/test_oauth_callback.py` with mocked `aexchange_code` and storage failure (fail-and-discard) scenarios in `src/webhooks/oauth_callback.py`
- [x] T024 [P] Add OAuth callback and production redirect URI setup section to `README.md` (callback-only flow, storage-first precedence, remove env refresh token after OAuth)
- [x] T025 [P] Add callback path routing and `WEBEX_INTEGRATION_REDIRECT_URI` portal registration notes to `infra/AWS_DEPLOYMENT.md`
- [x] T026 Run service app webhook regression check per `quickstart.md` section 7 (SC-005) and full success criteria SC-001 through SC-007

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies—start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 and feature 005 persistence—**BLOCKS all user stories**
- **User Story 1 (Phase 3)**: Depends on Phase 2—MVP; no dependency on US2/US3
- **User Story 2 (Phase 4)**: Depends on Phase 3 (callback + bootstrap must exist before webhook ensure wiring)
- **User Story 3 (Phase 5)**: Depends on Phase 3 callback handler (enhances same module); can parallel with US2 after T007–T009
- **Polish (Phase 6)**: Depends on desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Foundational complete → callback + persistence + startup bootstrap
- **User Story 2 (P2)**: US1 complete → webhook ensure on startup and post-callback
- **User Story 3 (P3)**: US1 callback handler exists → security/logging/HTML hardening

### Within Each User Story

- Persistence helpers (Phase 2) before callback handler
- Callback handler before startup bootstrap wiring (T007 before T011)
- Bootstrap before webhook ensure (T010 before T013–T015)

### Parallel Opportunities

- Phase 1: T002 parallel with T001
- Phase 2: T004 and T006 parallel after T003; T005 after T004
- Phase 4: T016 parallel with T013–T015 once bootstrap module exists
- Phase 5: T018–T020 parallel (same file—sequential preferred to avoid conflicts)
- Phase 6: T022, T023, T024, T025 all parallel

---

## Parallel Example: Foundational Phase

```bash
# After T003 completes, launch in parallel:
Task T004: "Add OAuth token serializers in src/persistence/token_storage.py"
Task T006: "Create src/webhooks/integration_bootstrap.py skeleton"

# Then sequential:
Task T005: "Extend DynamoDBTokenStorage integration get/set"
```

---

## Parallel Example: User Story 2 + User Story 3

```bash
# After US1 checkpoint (T012), different developers:
Developer A: T013–T017 (webhook ensure + register_webhooks.py)
Developer B: T018–T021 (callback security/logging — coordinate on oauth_callback.py)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: OAuth callback + DynamoDB persist + restart without env token
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → persistence layer extended for integration tokens
2. User Story 1 → OAuth callback MVP (SC-001, SC-002, SC-004)
3. User Story 2 → webhook auto-ensure idempotent (SC-007)
4. User Story 3 → security hardening (SC-003)
5. Polish → tests, docs, full quickstart (SC-005, SC-006)

### Parallel Team Strategy

1. Team completes Setup + Foundational together
2. One developer completes US1 (critical path)
3. US2 and US3 can overlap after US1 callback handler lands (different concerns: bootstrap vs handler polish)

---

## Notes

- SDK `aexchange_code` does **not** auto-persist—handler must call `set_integration_tokens` explicitly (`research.md` R2)
- SDK `arefresh` **does** persist via `set_integration_tokens`—startup refresh updates DynamoDB automatically
- Do **not** add server-side authorize route (FR-015; clarified callback-only)
- `POST /webhooks/webex` must remain unchanged (FR-010)—regression in quickstart section 7
- Stale webhooks at old URLs are not auto-deleted v1—document manual cleanup in README
- Commit after each task or logical group; stop at any checkpoint to validate story independently

---

## Task Summary

| Phase | Tasks | Story |
|-------|-------|-------|
| Setup | T001–T002 | — |
| Foundational | T003–T006 | — |
| US1 (P1) MVP | T007–T012 | OAuth callback + persistence + bootstrap |
| US2 (P2) | T013–T017 | Webhook ensure idempotent |
| US3 (P3) | T018–T021 | Secure callback UX |
| Polish | T022–T026 | Tests + docs + validation |
| **Total** | **26 tasks** | |

**MVP scope**: Phases 1–3 (T001–T012) — production OAuth callback with durable integration tokens and storage-first startup.
