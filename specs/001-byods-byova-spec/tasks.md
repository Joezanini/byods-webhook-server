# Tasks: BYODS CRUD & BYOVA Media Platform

**Input**: Design documents from `/specs/001-byods-byova-spec/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included where plan.md specifies unit/integration coverage. Not full TDD—targeted tests for SDK helpers, handlers, and webhook contract.

**Organization**: Tasks grouped by user story. SDK-only integration—no REST CRUD routes. Media via `BYOVAMediaServer` (v0.2.0+).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story label (US1–US4)

## Path Conventions

Single Python project at repository root: `src/`, `scripts/`, `tests/`, `main.py`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project structure and dependency alignment

- [x] T001 Create `src/` package layout per plan.md (`src/config/`, `src/common/`, `src/webhooks/`, `src/byods/`, `src/byova/`) with `__init__.py` files
- [x] T002 Update `requirements.txt` to `webex-byova[media]>=0.2.0` and add `pytest`, `pytest-asyncio`, `httpx` for tests
- [x] T003 [P] Update `.env.example` with `WEBEX_MEDIA_*` vars and optional `WEBEX_DATASOURCE_PUBLIC_URL` per SDK `MediaServerConfig.from_env()`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared config, logging, SDK bootstrap, and thin `main.py`—MUST complete before user stories

**⚠️ CRITICAL**: No user story work until this phase is complete

- [x] T004 [P] Implement `src/config/settings.py` loading app env vars (WEBEX_*, PORT, feature flags)
- [x] T005 [P] Implement `src/common/logging.py` with structured JSON formatter (org_id, operation, outcome fields)
- [x] T006 [P] Implement `src/common/middleware.py` with request ID middleware for HTTP routes
- [x] T007 Refactor `main.py` to thin FastAPI factory: BYOVA SDK `from_env()`, Integration `arefresh` on startup, `aclose` on shutdown
- [x] T008 Add `GET /health` and `GET /ready` endpoints in `main.py` (ready checks Integration token availability)
- [x] T009 Wire structured logging and request ID middleware into `main.py`

**Checkpoint**: Foundation ready—user story implementation can begin

---

## Phase 3: User Story 1 - Service App Lifecycle via Webhooks (Priority: P1) 🎯 MVP

**Goal**: Preserve production webhook flow; acknowledge authorize/deauthorize; store/remove org tokens; optional auto-register data source

**Independent Test**: Authorize and deauthorize in Control Hub; verify logs, HTTP 200 ack, HTTP 400 on invalid payload (quickstart Scenario 1)

### Implementation for User Story 1

- [x] T010 [US1] Extract `POST /webhooks/webex` handler to `src/webhooks/routes.py` preserving `sdk.ahandle_service_app_webhook` behavior from `main.py`
- [x] T011 [US1] Move `register_datasource_for_org`, `build_datasource_url`, and `_datasource_url_exists` to `src/webhooks/datasource_register.py` (behavior unchanged)
- [x] T012 [US1] Add structured webhook logging in `src/webhooks/routes.py` (org_id, event type, outcome; no secret leakage)
- [x] T013 [US1] Mount webhook router from `main.py`; preserve HTTP 400/503 responses and idempotent duplicate authorization handling

**Checkpoint**: User Story 1 fully functional—webhook-only MVP deployable

---

## Phase 4: User Story 2 - BYODS Data Source Management (Priority: P2)

**Goal**: SDK-only CRUD via shared service helpers and `scripts/manage_datasources.py` CLI—no REST endpoints

**Independent Test**: Full create→read→update→delete cycle via CLI; duplicate URL rejected; unauthorized org rejected (quickstart Scenario 2)

### Implementation for User Story 2

- [x] T014 [P] [US2] Add `src/byods/models.py` re-exporting SDK `DataSourceCreate`, `DataSourceUpdate`, and related types
- [x] T015 [US2] Implement `src/byods/service.py` with `list/get/create/update/delete` delegating to `OrgClient.data_sources` and `url_exists` duplicate guard
- [x] T016 [US2] Refactor `src/webhooks/datasource_register.py` to call `src/byods/service.py` for auto-register on authorized webhook
- [x] T017 [US2] Implement `scripts/manage_datasources.py` CLI per `contracts/sdk-operations.md` (`list`, `get`, `create`, `update`, `delete`, `schemas list/get`)
- [x] T018 [P] [US2] Add `tests/unit/test_byods_service.py` for duplicate URL guard and `OrgNotRegisteredError` mapping

**Checkpoint**: User Stories 1 and 2 work independently—webhooks + CLI CRUD

---

## Phase 5: User Story 3 - BYOVA Real-Time Media Sessions (Priority: P3)

**Goal**: Start SDK `BYOVAMediaServer` in-process; log session lifecycle; optional audio pass-through for testing

**Independent Test**: Server logs media listening on `WEBEX_MEDIA_PORT`; `grpcurl` lists VoiceVirtualAgent; WxCC call receives audio within 5s (quickstart Scenario 3)

### Implementation for User Story 3

- [x] T019 [P] [US3] Implement `src/byova/server.py` factory returning shared `BYOVAMediaServer.from_env()`
- [x] T020 [US3] Implement `src/byova/handlers.py` registering `@server.on` handlers for `session_start`, `audio_input`, `turn_started`, `turn_ended`, `session_end`, `error` with structured logging
- [x] T021 [US3] Implement `src/byova/lifecycle.py` and integrate `await media.start()` / `await media.stop()` into `main.py` FastAPI lifespan
- [x] T022 [US3] Add optional audio pass-through echo in `src/byova/handlers.py` for integration testing (configurable via env flag)
- [x] T023 [P] [US3] Add `tests/unit/test_byova_handlers.py` verifying handlers register on server and log key fields

**Checkpoint**: Full BYODS + BYOVA path—webhook, CRUD CLI, SDK media server

---

## Phase 6: User Story 4 - Production Operations & Security (Priority: P4)

**Goal**: Docker packaging, README ops docs, optional webhook rate limiting, health under concurrent load

**Independent Test**: `docker compose up` reaches healthy; logs structured on webhook/CRUD/media; secrets from env only (quickstart Scenario 4)

### Implementation for User Story 4

- [x] T024 [P] [US4] Add `Dockerfile` (Python 3.11-slim) installing `requirements.txt` and exposing HTTP + gRPC ports
- [x] T025 [P] [US4] Add `docker-compose.yml` mounting `.env`, exposing ports 8000 and `${WEBEX_MEDIA_PORT:-50051}`
- [x] T026 [US4] Update `README.md` with SDK CRUD CLI examples, `WEBEX_MEDIA_*` configuration, Render (HTTP) vs VPS/Docker (gRPC) deploy split
- [x] T027 [US4] Add optional rate limiting on `POST /webhooks/webex` in `src/common/middleware.py` (configurable `RATE_LIMIT_PER_MINUTE`)
- [x] T028 [P] [US4] Add `tests/integration/test_health.py` and `tests/contract/test_openapi_webhooks.py` per `contracts/openapi.yaml`

**Checkpoint**: Production-ready packaging and documentation

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup

- [x] T029 Run all `quickstart.md` scenarios; fix gaps found in code or docs
- [x] T030 [P] Remove dead code from `main.py` after module extraction; ensure `uvicorn main:app` entrypoint unchanged for `render.yaml`
- [x] T031 [P] Add `tests/integration/test_webhooks.py` with mocked SDK for authorize/deauthorize/invalid payload paths

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies—start immediately
- **Foundational (Phase 2)**: Depends on Phase 1—**blocks all user stories**
- **US1 (Phase 3)**: Depends on Phase 2
- **US2 (Phase 4)**: Depends on Phase 2; integrates with US1 auto-register (T016 after T015)
- **US3 (Phase 5)**: Depends on Phase 2; benefits from US2 data source URL alignment but independently testable via grpcurl
- **US4 (Phase 6)**: Depends on Phases 2–5 for complete README and Docker story
- **Polish (Phase 7)**: Depends on all desired story phases

### User Story Dependencies

| Story | Depends on | Notes |
|-------|------------|-------|
| US1 (P1) | Foundational | MVP—no other stories required |
| US2 (P2) | Foundational, US1 for auto-register refactor | CLI testable with `afetch_token_for_org` without running server |
| US3 (P3) | Foundational | SDK media server; data source URL from US2 recommended before WxCC test |
| US4 (P4) | US1–US3 | Cross-cutting ops and packaging |

### Within Each User Story

- Models/helpers before services
- Services before scripts or route integration
- Core implementation before tests for that story

### Parallel Opportunities

- **Phase 1**: T003 parallel with T001/T002 after T001 starts
- **Phase 2**: T004, T005, T006 in parallel; T007–T009 sequential
- **Phase 4**: T014 parallel with T015 prep; T018 parallel after T015
- **Phase 5**: T019 parallel; T023 after T020
- **Phase 6**: T024, T025, T028 in parallel
- **Phase 7**: T030, T031 in parallel

---

## Parallel Example: User Story 2

```bash
# Parallel after T015 is scoped:
Task T014: "Add src/byods/models.py"
Task T018: "Add tests/unit/test_byods_service.py" (after T015 completes)

# Sequential core:
Task T015 → T016 → T017
```

---

## Parallel Example: User Story 3

```bash
# Parallel:
Task T019: "Implement src/byova/server.py"
Task T023: "Add tests/unit/test_byova_handlers.py" (after T020)

# Sequential:
Task T019 → T020 → T021 → T022
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: quickstart Scenario 1
5. Deploy to Render (webhook + health)

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 → Webhook MVP on Render
3. US2 → SDK CRUD CLI + idempotent auto-register
4. US3 → SDK media server on VPS/Docker
5. US4 → Docker, README, rate limits, contract tests
6. Polish → quickstart validation

### Suggested MVP Scope

**User Story 1 only** (T001–T013): Production webhook receiver with preserved behavior. ~13 tasks.

### Full Feature Scope

**31 tasks** across 7 phases covering all four user stories.

---

## Notes

- No REST CRUD routes—operators use `scripts/manage_datasources.py` only
- No custom gRPC/proto—all media via `webex_byova.media.BYOVAMediaServer`
- Preserve existing `POST /webhooks/webex` response shapes for production compatibility
- `render.yaml` start command stays `uvicorn main:app`; gRPC requires VPS/Docker for US3
- Run `python scripts/ensure_sdk_media_protos.py` after pip install if SDK media stubs are missing from PyPI wheel
