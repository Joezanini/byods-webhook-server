# Implementation Plan: BYODS CRUD & BYOVA Media Platform

**Branch**: `001-byods-byova-spec` | **Date**: 2026-06-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-byods-byova-spec/spec.md`

## Summary

Extend the webhook server using **`webex-byova` v0.2.0+ as the sole Webex integration layer** (`pip install "webex-byova[media]"`). Preserve production-validated serviceApp webhooks (P1). Deliver BYODS CRUD (P2) through SDK calls in shared service helpers and operator **CLI scripts**—not HTTP REST routes. Deliver BYOVA media (P3) by starting the SDK's `BYOVAMediaServer` in the FastAPI lifespan with event handlers for logging and pass-through—no custom gRPC, proto vendoring, or gateway code. Harden production ops (P4) with structured logging, health/readiness, Docker, and env-only secrets.

The server exposes minimal HTTP surfaces (`POST /webhooks/webex`, `GET /health`, `GET /ready`). BYODS CRUD uses `OrgClient.data_sources` via scripts. Media uses SDK `BYOVAMediaServer` on `WEBEX_MEDIA_PORT` (default 50051).

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastAPI, uvicorn, `webex-byova[media]>=0.2.0`, python-dotenv, pytest/httpx (testing)

**Storage**: In-memory only (SDK `InMemoryTokenStorage`; SDK `ConversationStore` for media sessions). No persistent DB in this phase.

**Testing**: pytest with unit and integration markers; webhook, SDK helper, and media event handler tests

**Target Platform**: Linux server — Render (HTTP webhook + health), VPS/Docker (HTTP + gRPC media)

**Project Type**: FastAPI HTTP service + in-process SDK gRPC media server

**Performance Goals**: Webhook ack <3s p99 (SC-001); health <1s (SC-006); media audio within 5s of session start (SC-003)

**Constraints**: SDK-only for all Webex auth, BYODS, webhooks, and media; no operator REST API; no custom protocol code; webhook behavior unchanged

**Scale/Scope**: Integration operator / devrel testing; concurrent multi-org media sessions via SDK session isolation (SC-004)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verify against `.specify/memory/constitution.md`:

- [x] **SDK-First**: Webhooks via `ahandle_service_app_webhook`; CRUD via `OrgClient.data_sources`; media via `BYOVAMediaServer` + `MediaServerConfig.from_env()`. SDK handles gRPC proto, JWS verification, session/turn lifecycle.
- [x] **Webhook Integrity**: `POST /webhooks/webex` preserved; extracted to `src/webhooks/` without behavior change.
- [x] **Modular Architecture**: `src/webhooks/`, `src/byods/` (helpers), `src/byova/` (thin SDK media lifecycle + handlers), `src/common/`, `src/config/`.
- [x] **Production Reliability**: Structured logging on webhooks and media events, `/health` + `/ready`, env config, Dockerfile, async I/O.
- [x] **Security by Default**: SDK `verify_tokens` (JWS) on gRPC; webhook validation via SDK; secrets env-only.
- [x] **Incremental Delivery**: P1 webhook → config refactor → P2 SDK CRUD scripts → P3 SDK media server → P4 ops → tests.

**Post-Phase 1 re-check**: All gates pass. `src/byova/` contains only SDK wiring and logging handlers—no custom gRPC servicer.

## Project Structure

### Documentation (this feature)

```text
specs/001-byods-byova-spec/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── openapi.yaml          # Webhook + health only
│   └── sdk-operations.md     # SDK CRUD + media event contract
└── tasks.md
```

### Source Code (repository root)

```text
byods-webhook-server/
├── main.py                         # App factory; lifespan starts SDK media server
├── src/
│   ├── config/
│   │   └── settings.py             # Env settings (WEBEX_* + WEBEX_MEDIA_*)
│   ├── common/
│   │   ├── logging.py              # Structured JSON formatter
│   │   └── middleware.py           # Request ID on webhook routes
│   ├── webhooks/
│   │   ├── routes.py               # POST /webhooks/webex (preserved)
│   │   └── datasource_register.py  # Auto-register on authorized (moved)
│   ├── byods/
│   │   ├── service.py              # SDK OrgClient CRUD + duplicate URL guard
│   │   └── models.py               # Thin wrappers around SDK models
│   └── byova/
│       ├── server.py               # BYOVAMediaServer.from_env() factory
│       ├── handlers.py             # @server.on(...) logging + optional pass-through
│       └── lifecycle.py            # start/stop in FastAPI lifespan
├── scripts/
│   ├── register_webhooks.py
│   └── manage_datasources.py
├── tests/
│   ├── unit/
│   └── integration/
├── Dockerfile
├── docker-compose.yml              # Exposes HTTP + WEBEX_MEDIA_PORT
├── requirements.txt
├── render.yaml
├── .env.example
└── README.md
```

**Structure Decision**: HTTP for Webex webhook ingress. SDK `BYOVAMediaServer` runs in-process on `WEBEX_MEDIA_PORT`. `src/byova/` is a thin adapter—no `proto/` directory, no custom servicers.

## Complexity Tracking

> No constitution violations requiring justification.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Phase 0: Research Summary

See [research.md](./research.md):

| Topic | Decision |
|-------|----------|
| Webex integration | `webex-byova[media]>=0.2.0` only |
| BYODS CRUD | SDK `OrgClient` via CLI + `src/byods/service.py` |
| Media transport | SDK `BYOVAMediaServer` with `MediaServerConfig.from_env()` |
| HTTP surfaces | Webhook + health/readiness only |
| Dual ports | HTTP `PORT` (8000) + gRPC `WEBEX_MEDIA_PORT` (50051) |
| Data source URL | `{public host}{WEBEX_DATASOURCE_PATH_SUFFIX}` aligned with gRPC endpoint |

## Phase 1: Design Summary

### Data Model

See [data-model.md](./data-model.md). Media sessions map to SDK `MediaSession` / `TurnContext`.

### Contracts

- HTTP: [contracts/openapi.yaml](./contracts/openapi.yaml)
- SDK: [contracts/sdk-operations.md](./contracts/sdk-operations.md) — CRUD scripts + media event handlers

### Validation Guide

See [quickstart.md](./quickstart.md).

## Implementation Phases (for tasks.md)

### Phase A — Foundation (config + refactor)

1. Bump `requirements.txt` to `webex-byova[media]>=0.2.0`
2. Add `src/config/settings.py`; migrate env reads from `main.py`
3. Extract webhook routes + auto-register to `src/webhooks/`
4. Structured logging + request ID middleware
5. Add `/ready` endpoint
6. Update `.env.example` with `WEBEX_MEDIA_*` vars (see SDK `MediaServerConfig.from_env`)

### Phase B — BYODS CRUD via SDK (P2)

1. `src/byods/service.py` — SDK delegation, duplicate URL guard
2. Refactor webhook auto-register to use shared service
3. `scripts/manage_datasources.py` CLI
4. Unit + integration tests

### Phase C — BYOVA Media via SDK (P3)

1. `src/byova/server.py` — `BYOVAMediaServer.from_env()`
2. `src/byova/handlers.py` — register handlers for `session_start`, `audio_input`, `session_end`, `error` (structured logging; optional audio pass-through echo for testing)
3. `src/byova/lifecycle.py` — `await media.start()` / `await media.stop()` in FastAPI lifespan alongside SDK bootstrap
4. Ensure data source URL from auto-register points at public gRPC endpoint
5. Integration test: in-process handler fires on simulated session events (SDK test patterns)

### Phase D — Production Ops (P4)

1. Dockerfile + docker-compose (expose ports 8000 + 50051)
2. README: SDK CRUD scripts + media env vars + Render vs VPS deploy split
3. Optional webhook rate limiting
4. Sandbox integration test markers

## Risk Register

| Risk | Mitigation |
|------|------------|
| Render HTTP-only (no gRPC) | Document VPS/Docker for media; webhook-only on Render |
| Data source URL vs gRPC host mismatch | `manage_datasources.py get`; env `WEBEX_DATASOURCE_PUBLIC_URL` |
| In-memory tokens lost on restart | Integration refresh + re-webhook or script re-fetch |
| Media optional dep missing | Pin `webex-byova[media]` in requirements.txt |

## Next Step

Run `/speckit-tasks` to generate dependency-ordered `tasks.md` from this plan.
