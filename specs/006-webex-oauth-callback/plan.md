# Implementation Plan: Webex Integration OAuth Callback

**Branch**: `006-webex-oauth-callback` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-webex-oauth-callback/spec.md`

## Summary

Add a production `GET` OAuth callback route (path from `WEBEX_INTEGRATION_REDIRECT_URI`) that exchanges Webex authorization codes via SDK `aexchange_code`, persists integration tokens to DynamoDB (`INTEGRATION/CREDS`), and runs idempotent webhook verification via SDK `aensure_service_app_webhooks` on callback success and startup. Extend `DynamoDBTokenStorage` to durably store integration tokens (superseding feature 005 in-memory-only integration storage). Startup loads storage-first with env refresh token fallback. Existing `POST /webhooks/webex` unchanged.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastAPI, uvicorn, `webex-byova[media]>=0.2.0`, boto3/aioboto3, cryptography (Fernet), python-dotenv, pytest

**Storage**: Amazon DynamoDB `byods-app-state` — new singleton item `PK=INTEGRATION`, `SK=CREDS` (encrypted); feature 005 org/catalog/audit items unchanged

**Testing**: pytest unit tests for integration token persistence; integration tests for callback handler (mocked SDK exchange); manual quickstart scenarios

**Target Platform**: Linux — local Docker/DynamoDB Local, AWS ECS Fargate (existing `infra/stack.py`)

**Project Type**: FastAPI HTTP + SDK gRPC media server (extends features 001, 005)

**Performance Goals**: OAuth callback p95 <3s (dominated by Webex token exchange); startup webhook ensure adds ≤2s when tokens present; no impact on webhook/media hot paths

**Constraints**: SDK-first OAuth; callback-only (no authorize route); fail-and-discard on persistence failure; storage-over-env precedence; verify-first webhook registration

**Scale/Scope**: Single integration token set per deployment; infrequent OAuth (manual developer action); existing webhook QPS unchanged

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verify against `.specify/memory/constitution.md`:

- [x] **SDK-First**: `aexchange_code`, `arefresh`, `aensure_service_app_webhooks` — no custom OAuth HTTP
- [x] **Webhook Integrity**: `POST /webhooks/webex` preserved; new GET callback route only
- [x] **Modular Architecture**: Callback in webhook/auth module; persistence in `src/persistence/`; no BYOVA media leakage
- [x] **Production Reliability**: Structured logging, `/ready` integration gate, env config, rate limit on callback
- [x] **Security by Default**: Fernet encryption, secrets in env only, no token leakage in HTML/logs, input validation on query params
- [x] **Incremental Delivery**: P1 callback + persistence → P2 startup/webhook ensure → P3 HTML UX/tests → docs

**Post-Phase 1 re-check**: All gates pass. Feature 005 assumption (integration tokens in-memory) intentionally superseded per spec clarifications — not a constitution violation; documented in research R3.

## Project Structure

### Documentation (this feature)

```text
specs/006-webex-oauth-callback/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── oauth-callback.md
│   └── persistence-integration-tokens.md
└── tasks.md                    # Phase 2 (/speckit-tasks)
```

### Source Code (repository root — additions/changes)

```text
byods-webhook-server/
├── main.py                           # MODIFY: storage-first bootstrap; post-start webhook ensure
├── .env.example                      # MODIFY: production redirect URI example; refresh token optional note
├── README.md                         # MODIFY: OAuth callback section
├── src/
│   ├── config/settings.py            # MODIFY: integration_redirect_path property (parsed from URI)
│   ├── persistence/
│   │   └── token_storage.py          # MODIFY: DynamoDB integration token get/set
│   ├── webhooks/
│   │   ├── routes.py                 # MODIFY: include oauth callback router or routes
│   │   ├── oauth_callback.py         # NEW: GET callback handler + HTML responses
│   │   └── integration_bootstrap.py  # NEW: startup token load + webhook ensure helper
│   └── common/
│       └── templates/                # NEW (optional): minimal oauth success/error HTML
├── scripts/
│   └── register_webhooks.py          # MODIFY: production redirect URI docs + get_authorization_url flow
├── tests/
│   ├── unit/
│   │   ├── test_token_storage.py     # MODIFY: integration token round-trip
│   │   └── test_oauth_callback.py    # NEW: handler tests (mock SDK)
│   └── integration/
│       └── test_oauth_callback.py    # NEW: persistence + callback flow
└── infra/
    └── AWS_DEPLOYMENT.md             # MODIFY: redirect URI + callback path routing
```

**Structure Decision**: OAuth callback lives in `src/webhooks/` alongside service app webhook routes (auth/webhook module boundary). Integration bootstrap extracted to avoid bloating `main.py` lifespan.

## Complexity Tracking

> No constitution violations requiring justification.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Phase 0: Research Summary

See [research.md](./research.md):

| Topic | Decision |
|-------|----------|
| Callback path | Parsed from `WEBEX_INTEGRATION_REDIRECT_URI` |
| Code exchange | SDK `integration.aexchange_code(code)` |
| Integration persistence | DynamoDB `INTEGRATION/CREDS`, Fernet encrypted |
| Startup precedence | Storage first; env refresh token fallback |
| Webhook registration | SDK `aensure_service_app_webhooks` (list-then-create) |
| Persistence failure | Fail-and-discard; no in-memory retention |
| OAuth initiation | External only (portal or script); no authorize route |
| CSRF state | Best-effort when present; optional in v1 |

## Phase 1: Design Summary

See [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md).

### DynamoDB addition

| PK | SK | Purpose |
|----|-----|---------|
| `INTEGRATION` | `CREDS` | Encrypted integration OAuth tokens (singleton) |

### Application wiring

1. **Callback** (`GET {redirect_path}`): extract query → handle errors → `aexchange_code` → `set_integration_tokens` → `aensure_service_app_webhooks` → HTML response.
2. **Startup**: `bootstrap_integration(sdk, settings)` — load storage → refresh or env fallback → webhook ensure.
3. **Token storage**: `DynamoDBTokenStorage.set/get_integration_tokens` read/write `INTEGRATION/CREDS`.
4. **Ready probe**: Unchanged; requires successful integration bootstrap.

### Key implementation notes

- `aexchange_code` does not persist; handler must call `set_integration_tokens` explicitly.
- `arefresh` persists via storage — startup refresh updates DynamoDB automatically.
- Route path MUST match registered Webex redirect URI path component.
- Do not mount localhost callback on FastAPI when using `register_webhooks.py` local listener (different deployment modes).

### Delivery order (for `/speckit-tasks`)

1. **Foundation**: `settings.integration_redirect_path`; OAuth token serializers in `token_storage.py`
2. **P1**: DynamoDB integration persistence; callback route + HTML; fail-and-discard handling
3. **P1**: Startup bootstrap refactor (storage-first); update `main.py` lifespan
4. **P2**: Post-callback + startup `aensure_service_app_webhooks`; update `register_webhooks.py`
5. **P3**: Unit/integration tests; `.env.example`, README, AWS_DEPLOYMENT; quickstart validation

### Dependencies

- Feature 005 persistent app state (DynamoDB table, encryption, `DynamoDBTokenStorage` for org tokens)
- Feature 001 webhook handler (unchanged contract)
- `webex-byova>=0.2.0` with `aexchange_code`, `aensure_service_app_webhooks`

### Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Redirect URI mismatch | Single-source from env; document portal registration in quickstart |
| Exchange succeeds, persist fails | Fail-and-discard; clear error HTML; operator retries OAuth |
| Stale webhooks at old URL | Document manual cleanup; `aensure` only creates missing |
| Env token overrides storage confusion | Storage-first precedence; README says remove env after OAuth |
| Local vs production redirect URI | Two modes documented: localhost script vs production callback route |

## Phase 2 Preview

`/speckit-tasks` will generate dependency-ordered tasks from this plan. No `tasks.md` created by this command.
