# Research: BYODS CRUD & BYOVA Media Platform

**Feature**: `001-byods-byova-spec` | **Date**: 2026-06-07 | **Revised**: 2026-06-07 (SDK media APIs in v0.2.0)

## R1: Modular refactor from flat `main.py`

**Decision**: Incrementally extract webhook and auto-registration into `src/webhooks/`. Add thin `src/byova/` for SDK media lifecycle. `main.py` remains a thin FastAPI factory.

**Rationale**: Constitution Principle III; preserves webhook behavior while enabling parallel BYODS and media modules.

**Alternatives considered**:
- *REST CRUD routes* — rejected (SDK-only, no operator REST API).
- *Custom gRPC in-repo* — rejected now that SDK ships `BYOVAMediaServer`.

---

## R2: BYODS CRUD via SDK `OrgClient` (no REST)

**Decision**: CRUD in `src/byods/service.py` + `scripts/manage_datasources.py` CLI. No HTTP REST endpoints.

**Rationale**: SDK `DataSourceResource` implements async CRUD with token refresh. Operators use CLI like `register_webhooks.py`.

**CLI token bootstrap**: `integration.arefresh` + `service_app.afetch_token_for_org(org_id)` after Control Hub authorization.

---

## R3: Authentication (SDK paths only)

**Decision**:
- Webhooks: `sdk.ahandle_service_app_webhook`
- CRUD scripts: Integration refresh + `afetch_token_for_org`
- Media gRPC: SDK `MediaServerConfig.verify_tokens=True` (built-in `JWSVerifier` in gRPC servicer)

**Rationale**: No custom auth layers.

---

## R4: BYOVA media via SDK `BYOVAMediaServer` (v0.2.0+)

**Decision**: Use `webex_byova.media.BYOVAMediaServer` with `MediaServerConfig.from_env()` (`WEBEX_MEDIA_*` env vars). Start/stop in FastAPI lifespan. Register event handlers in `src/byova/handlers.py` for logging and optional test pass-through.

**Rationale**: `webex-byova` v0.2.0 ships a complete gRPC media server—`ProcessCallerInput`, session/turn management, JWS verification, audio chunking, barge-in, DTMF. Constitution SDK-First principle satisfied without gateway fork or proto vendoring.

**SDK surface** (install `webex-byova[media]`):
- `BYOVAMediaServer.from_env()` / `MediaServerConfig.from_env()`
- `@server.on("session_start")`, `"audio_input"`, `"turn_started"`, `"turn_ended"`, `"session_end"`, `"error"`
- `MediaSession.play_prompt()`, `collect_input()`, `end_session()`
- Optional `WebSocketProxyConnector` for external agent backends (out of scope unless needed)

**Alternatives considered**:
- *Defer media* — obsolete; SDK now ships media APIs.
- *webex-byova-gateway-python fork* — rejected; duplicates SDK.
- *Custom proto/gRPC servicer* — rejected; SDK `_internal/grpc_service.py` handles protocol.

---

## R5: Dual-server deployment topology

**Decision**:
- **HTTP** (`PORT`, default 8000): `POST /webhooks/webex`, `GET /health`, `GET /ready`
- **gRPC** (`WEBEX_MEDIA_PORT`, default 50051): SDK `BYOVAMediaServer`
- **Data source URL**: `WEBEX_DATASOURCE_PUBLIC_URL` or `{origin of WEBEX_WEBHOOK_TARGET_URL}{WEBEX_DATASOURCE_PATH_SUFFIX}` must match public gRPC endpoint WxCC uses

**Rationale**: Render exposes HTTP only; full BYOVA path needs VPS/Docker with port 50051 reachable. README documents split deploy.

---

## R6: Configuration

**Decision**: `src/config/settings.py` for app-level env; media uses SDK `MediaServerConfig.from_env()` directly (no re-mapping unless needed for tests).

**Key env groups**:
- `WEBEX_INTEGRATION_*`, `WEBEX_SA_*` — auth (existing)
- `WEBEX_DATASOURCE_*` — auto-register defaults (existing)
- `WEBEX_MEDIA_HOST`, `WEBEX_MEDIA_PORT`, `WEBEX_MEDIA_VERIFY_TOKENS`, etc. — media server

---

## R7: Observability

**Decision**:
- Structured JSON logs on webhook routes and media event handlers (org/conversation_id, session_id, operation, outcome)
- Request ID middleware on HTTP only
- SDK handles internal gRPC logging at `WEBEX_MEDIA_LOG_LEVEL`

---

## R8: Rate limiting

**Decision**: Optional rate limit on `POST /webhooks/webex` only. No REST API to protect.

---

## R9: Testing strategy

**Decision**:
- pytest for webhooks, health, BYODS service helpers
- Media handler unit tests (mock `MediaSession` / events)
- Integration tests with sandbox org and live gRPC (optional CI)
- Contract reference: [sdk-operations.md](./contracts/sdk-operations.md)

---

## R10: Container packaging

**Decision**: Dockerfile + docker-compose exposing HTTP (8000) and gRPC (50051). `render.yaml` for HTTP webhook deploy only.

---

## R11: Default schema and audio metadata

**Decision**: Unchanged voice VA defaults. Schema discovery via `manage_datasources.py schemas`. Media defaults: `audio_mode=chunked`, `sample_rate=8000`, `encoding=mulaw` per SDK `MediaServerConfig`.
