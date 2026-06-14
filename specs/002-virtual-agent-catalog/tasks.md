# Tasks: Virtual Agent Catalog for Flow Designer

**Input**: Design documents from `/specs/002-virtual-agent-catalog/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included per plan.md (catalog unit tests, ListVirtualAgents integration smoke, handler logging tests). Not full TDD—targeted coverage for validation and discovery logging.

**Organization**: Tasks grouped by user story. Extends feature `001` BYOVA media server. Requires `webex-byova[media]>=0.3.0` (catalog API + `list_virtual_agents` event).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story label (US1–US3)

## Path Conventions

Single Python project at repository root: `src/`, `config/`, `tests/`, `main.py`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependency alignment, sample catalog, and environment documentation

- [x] T001 Update `requirements.txt` to `webex-byova[media]>=0.3.0` (catalog + `list_virtual_agents` event; blocks until SDK release published or editable local install)
- [x] T002 [P] Create `config/virtual_agents.json` with six Cisco demo agents (Travel Booking Agent, Credit card service, Insurance service, Barge-in Travel Booking Agent, Scripted Agent, Barge-in General Agent) per `contracts/virtual-agent-catalog.md`
- [x] T003 [P] Add `WEBEX_VIRTUAL_AGENTS_CONFIG=config/virtual_agents.json` to `.env.example` with comment describing catalog override path

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Catalog loader, settings, logging extensions, and media server factory wiring—MUST complete before user stories

**⚠️ CRITICAL**: No user story work until this phase is complete. Confirm SDK `>=0.3.0` exposes `VirtualAgentConfig`, `MediaServerConfig.virtual_agents`, `ListVirtualAgentsEvent`, and `@server.on("list_virtual_agents")` before proceeding.

- [x] T004 Verify installed `webex-byova` version satisfies `>=0.3.0` API from `contracts/virtual-agent-catalog.md`; reinstall from PyPI or editable SDK path if needed
- [x] T005 [P] Add `virtual_agents_config_path` field to `src/config/settings.py` loaded from `WEBEX_VIRTUAL_AGENTS_CONFIG` (default `config/virtual_agents.json`)
- [x] T006 Implement `src/byova/catalog.py` with `load_catalog(path)`, ID coercion to string, `to_sdk_config(entries)`, and validation for non-empty names, unique IDs, and at-most-one default
- [x] T007 [P] Extend `src/common/logging.py` `StructuredJsonFormatter` and `log_event()` to support optional `agent_count`, `tracking_id`, and `agent_names` fields for discovery logs
- [x] T008 Modify `src/byova/server.py` `create_media_server()` to load catalog via `load_catalog(settings.virtual_agents_config_path)` and pass `virtual_agents` into `MediaServerConfig.from_env().model_copy(update=...)`

**Checkpoint**: Foundation ready—catalog loads into SDK config; user story implementation can begin

---

## Phase 3: User Story 1 - Discover Virtual Agents in Flow Designer (Priority: P1) 🎯 MVP

**Goal**: Flow Designer (and grpcurl) receive populated `ListVirtualAgents` response; every discovery request emits INFO-level console log

**Independent Test**: Run server with `LOG_JSON=false`; `grpcurl -plaintext -H 'trackingid: test-001' localhost:50051 com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents` returns six agents; console shows `Flow Designer requested virtual agent list` INFO line (quickstart Scenario 2)

### Implementation for User Story 1

- [x] T009 [US1] Log `Virtual agent catalog loaded: N agents from <path>` at INFO in `src/byova/lifecycle.py` `start_media_server()` after catalog is wired
- [x] T010 [US1] Register `@server.on("list_virtual_agents")` handler in `src/byova/handlers.py` that calls `log_event()` at INFO with `operation=list_virtual_agents`, `org_id=customer_org_id`, `agent_count`, `tracking_id`, and human-readable message per `plan.md` discovery logging contract
- [x] T011 [P] [US1] Add `tests/unit/test_virtual_agent_catalog.py` covering happy-path load, six-agent sample file, and string ID coercion from numeric JSON values
- [x] T012 [P] [US1] Add `tests/integration/test_list_virtual_agents.py` smoke test asserting `ListVirtualAgents` returns expected agent count and names when media server starts with default catalog

**Checkpoint**: User Story 1 complete—Flow Designer picker populated; discovery visible in console logs

---

## Phase 4: User Story 2 - Operator-Managed Agent Catalog (Priority: P2)

**Goal**: Operators customize catalog via JSON file; invalid configs fail fast at startup with actionable errors; changes apply after restart

**Independent Test**: Rename an agent in `config/virtual_agents.json`, restart server, grpcurl shows new name; break catalog (duplicate ID), server exits before binding port 50051 with clear stderr (quickstart Scenarios 4 and 6)

### Implementation for User Story 2

- [x] T013 [US2] Add `CatalogLoadError` (or reuse SDK `MediaConfigError`) in `src/byova/catalog.py` with actionable messages for missing file, invalid JSON, empty array, duplicate `virtual_agent_id`, and multiple `is_default: true` entries (FR-004, FR-005, FR-009)
- [x] T014 [US2] Ensure `src/byova/lifecycle.py` and `src/byova/server.py` propagate catalog validation errors before `await media.start()` so server never advertises silent empty list
- [x] T015 [P] [US2] Extend `tests/unit/test_virtual_agent_catalog.py` with negative cases: missing file, duplicate IDs, multiple defaults, empty catalog, and invalid JSON structure

**Checkpoint**: User Stories 1 and 2 complete—operator-editable catalog with fail-fast validation

---

## Phase 5: User Story 3 - Agent Selection Carried Into Live Calls (Priority: P3)

**Goal**: `virtual_agent_id` from Flow Designer selection appears in `session_start` logs; unknown IDs log WARNING without crashing session

**Independent Test**: Place test call (or simulate `session_start` with metadata) using agent id `1`; console shows `virtual_agent_id=1` at INFO; id `99` produces WARNING with `catalog_match=false` (quickstart Scenario 5)

### Implementation for User Story 3

- [x] T016 [US3] Extend `session_start` handler in `src/byova/handlers.py` to log `virtual_agent_id` and `customer_org_id` from `event.metadata` at INFO (requires SDK `>=0.3.0` metadata enrichment)
- [x] T017 [US3] Add catalog membership check in `src/byova/handlers.py` `session_start` using loaded catalog; log WARNING with `operation=session_start`, `outcome=warning` when `virtual_agent_id` not in catalog; continue session without crash
- [x] T018 [P] [US3] Extend `tests/unit/test_byova_handlers.py` with tests for session_start agent id logging and unknown-id warning behavior

**Checkpoint**: All user stories complete—discovery, operator config, and runtime agent context

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, container packaging, and end-to-end validation

- [x] T019 [P] Update `README.md` with virtual agent catalog section: `WEBEX_VIRTUAL_AGENTS_CONFIG`, Flow Designer prerequisites, discovery console logging, and `LOG_JSON=false` tip for readable lines
- [x] T020 [P] Ensure `Dockerfile` copies `config/virtual_agents.json` into image (or document volume mount in `docker-compose.yml`) so container deployments ship the sample catalog
- [x] T021 Run `quickstart.md` Scenarios 1–2 and document pass/fail in implementation notes; confirm INFO log line appears per `ListVirtualAgents` call

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies—start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 + SDK `>=0.3.0` availability—**BLOCKS all user stories**
- **User Story 1 (Phase 3)**: Depends on Foundational—MVP deliverable
- **User Story 2 (Phase 4)**: Depends on Foundational; extends `catalog.py` validation (can follow US1 or run in parallel after T006)
- **User Story 3 (Phase 5)**: Depends on Foundational + SDK session metadata; independent of US2 completion
- **Polish (Phase 6)**: Depends on desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Requires Phase 2 only—no dependency on US2/US3
- **User Story 2 (P2)**: Requires Phase 2; validation hardening extends US1 catalog loader—testable independently via startup failure and config edit scenarios
- **User Story 3 (P3)**: Requires Phase 2 + SDK session metadata—testable independently via session_start logs without re-testing Flow Designer picker

### Within Each User Story

- Implementation before integration tests for that story
- US1 handlers depend on T008 server wiring and T007 logging extensions
- US2 validation extends T006 catalog.py (complete T006 before T013–T015)
- US3 handlers extend existing `src/byova/handlers.py` (complete T010 before T016–T017)

### Parallel Opportunities

- **Phase 1**: T002 and T003 in parallel after T001
- **Phase 2**: T005 and T007 in parallel after T006 is scoped; T007 can start once T006 interface is defined
- **Phase 3**: T011 and T012 in parallel after T010
- **Phase 4**: T015 in parallel with T013–T014 if different test cases
- **Phase 5**: T018 in parallel with T016–T017 once handler contract is clear
- **Phase 6**: T019 and T020 in parallel
- **Cross-story**: After Phase 2, US2 (validation) and US3 (session logging) can proceed in parallel with US1 polish if staffed separately

---

## Parallel Example: User Story 1

```bash
# After T010 completes, launch tests together:
Task T011: "Add tests/unit/test_virtual_agent_catalog.py happy-path cases"
Task T012: "Add tests/integration/test_list_virtual_agents.py smoke test"

# Phase 2 parallel pair:
Task T005: "Add virtual_agents_config_path to src/config/settings.py"
Task T007: "Extend src/common/logging.py for discovery fields"
```

---

## Parallel Example: User Story 2 + User Story 3

```bash
# After Phase 2 checkpoint, different developers:
Developer A: T013–T015 (catalog validation hardening)
Developer B: T016–T018 (session_start agent context logging)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (**confirm SDK >=0.3.0**)
3. Complete Phase 3: User Story 1 (discovery + console logging)
4. **STOP and VALIDATE**: quickstart Scenario 2—grpcurl returns six agents; INFO log visible
5. Demo in Flow Designer if data source registered

### Incremental Delivery

1. Setup + Foundational → catalog wired into SDK
2. User Story 1 → Flow Designer picker works + discovery logs (MVP)
3. User Story 2 → fail-fast validation + operator config edits
4. User Story 3 → runtime `virtual_agent_id` in session logs
5. Polish → README, Docker, full quickstart validation

### Parallel Team Strategy

1. Team completes Phase 1–2 together (SDK version gate is critical path)
2. Once Foundational done:
   - Developer A: US1 (T009–T012)
   - Developer B: US2 (T013–T015)
   - Developer C: US3 (T016–T018)
3. Merge and run Phase 6 polish

---

## Notes

- SDK `webex-byova>=0.3.0` is an **external blocking dependency**; Phase 2 T004 must pass before application tasks succeed. If SDK not yet released, use editable install from `byova-sdk-python` repo during development.
- Discovery logging is a **user-requested requirement**: every `ListVirtualAgents` call MUST emit exactly one INFO line (plain or JSON per `LOG_JSON`).
- Do not modify `src/webhooks/` or `scripts/manage_datasources.py` (FR-011).
- `[P]` tasks = different files, no incomplete-task dependencies
- Commit after each task or logical group; stop at any checkpoint to validate story independently
