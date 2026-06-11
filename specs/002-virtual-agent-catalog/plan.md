# Implementation Plan: Virtual Agent Catalog for Flow Designer

**Branch**: `002-virtual-agent-catalog` | **Date**: 2026-06-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-virtual-agent-catalog/spec.md`  
**User addition**: Include **console-level INFO logging** whenever Flow Designer (or WxCC) calls `ListVirtualAgents`.

## Summary

Wire a file-backed virtual agent catalog into the BYOVA media server so Flow Designer can populate the IVR Virtual Agent picker. Load and validate `config/virtual_agents.json` (Cisco sample format, six demo agents shipped by default). Delegate gRPC `ListVirtualAgents` to `webex-byova` SDK (requires `>=0.3.0` catalog support—v0.2.0 returns an empty list today). Register an application handler on the new SDK `list_virtual_agents` event to emit **INFO-level stdout logs** on every discovery request, including `customer_org_id`, `agent_count`, `agent_names`, and `tracking_id` when present. Extend session-start logging with `virtual_agent_id` for P3. No webhook or BYODS CRUD changes.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FastAPI, uvicorn, `webex-byova[media]>=0.3.0` (catalog + discovery event), python-dotenv, pytest (testing)

**Storage**: JSON catalog file on disk; in-memory list at runtime. No database.

**Testing**: pytest unit tests for catalog validation/loader; integration test for `ListVirtualAgents` response shape; manual/grpcurl quickstart for console log verification

**Target Platform**: Linux server — local dev, Docker, VPS (gRPC port 50051 exposed for WxCC/Flow Designer)

**Project Type**: FastAPI HTTP service + in-process SDK gRPC media server (extends feature `001`)

**Performance Goals**: Catalog load <100ms at startup; `ListVirtualAgents` response <500ms p99 (trivial for six static entries)

**Constraints**: SDK-only gRPC; no custom servicer; webhook integrity preserved; discovery logs at INFO to stdout (visible in `uvicorn`/Docker console without DEBUG)

**Scale/Scope**: Single shared catalog for all orgs; six sample agents; operator-editable JSON config

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verify against `.specify/memory/constitution.md`:

- [x] **SDK-First**: `ListVirtualAgents` and `ProcessCallerInput` remain SDK-implemented; catalog passed via `MediaServerConfig.virtual_agents`; discovery observability via SDK `list_virtual_agents` event—no proto vendoring or parallel servicer in this repo.
- [x] **Webhook Integrity**: `POST /webhooks/webex` and auto-register behavior unchanged (FR-011).
- [x] **Modular Architecture**: Catalog load/validate in `src/byova/catalog.py`; discovery logging in `src/byova/handlers.py` (or `discovery.py`); settings in `src/config/settings.py`; no coupling to `src/webhooks/` or `src/byods/`.
- [x] **Production Reliability**: INFO console logs on every discovery request; startup fail-fast on invalid catalog; structured JSON logs when `LOG_JSON=true`; env-driven catalog path.
- [x] **Security by Default**: Discovery inherits `WEBEX_MEDIA_VERIFY_TOKENS`; no new HTTP admin routes; catalog file is non-secret (names/ids only).
- [x] **Incremental Delivery**: SDK catalog API → app catalog loader → discovery logging → session agent context → sample file + quickstart → tests.

**Post-Phase 1 re-check**: All gates pass. SDK enhancement is upstream dependency, not a constitution violation in this repo.

## Project Structure

### Documentation (this feature)

```text
specs/002-virtual-agent-catalog/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── virtual-agent-catalog.md
└── tasks.md                    # Phase 2 (/speckit-tasks)
```

### Source Code (repository root — additions/changes)

```text
byods-webhook-server/
├── config/
│   └── virtual_agents.json           # NEW: six-agent Cisco sample catalog
├── src/
│   ├── config/
│   │   └── settings.py               # + WEBEX_VIRTUAL_AGENTS_CONFIG
│   ├── common/
│   │   └── logging.py                # + optional fields: agent_count, tracking_id, agent_names
│   └── byova/
│       ├── catalog.py                # NEW: load, validate, SDK mapping
│       ├── server.py                 # MODIFY: pass catalog into MediaServerConfig
│       ├── handlers.py               # MODIFY: list_virtual_agents + session_start agent id logs
│       └── lifecycle.py              # MODIFY: log catalog load count at startup
├── tests/
│   ├── unit/
│   │   └── test_virtual_agent_catalog.py   # NEW: validation + loader
│   └── integration/
│       └── test_list_virtual_agents.py     # NEW: grpcurl-style RPC smoke (if feasible)
├── .env.example                      # + WEBEX_VIRTUAL_AGENTS_CONFIG
└── README.md                         # + catalog + discovery logging section
```

**Structure Decision**: Extend existing `src/byova/` thin adapter pattern from feature `001`. New `config/virtual_agents.json` at repo root mirrors Cisco sample layout.

## Complexity Tracking

> No constitution violations requiring justification.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Phase 0: Research Summary

See [research.md](./research.md):

| Topic | Decision |
|-------|----------|
| Discovery protocol | gRPC `ListVirtualAgents` on media endpoint |
| Catalog format | Cisco `virtual_agents.json` JSON array |
| SDK strategy | Extend `webex-byova>=0.3.0`; app loads JSON → `MediaServerConfig.virtual_agents` |
| Console logging | INFO on `list_virtual_agents` event; plain text when `LOG_JSON=false` |
| Validation | Fail-fast at startup on duplicates, multiple defaults, empty catalog |
| Session agent id | SDK forwards `virtual_agent_id` into `SessionStartEvent.metadata` |

## Phase 1: Design Summary

See [data-model.md](./data-model.md), [contracts/virtual-agent-catalog.md](./contracts/virtual-agent-catalog.md), [quickstart.md](./quickstart.md).

### SDK changes (upstream `webex-byova`, blocking)

1. Add `VirtualAgentConfig` pydantic model.
2. Add `virtual_agents: list[VirtualAgentConfig]` to `MediaServerConfig` (optional env loader deferred; app passes programmatically).
3. Implement `ListVirtualAgents` to map config entries to `ListVAResponse`.
4. Add `ListVirtualAgentsEvent` and dispatch `list_virtual_agents` before returning response; extract `trackingid` from gRPC metadata.
5. Include `virtual_agent_id` and `customer_org_id` in `SessionStartEvent.metadata` from first `VoiceVARequest`.

### Application changes (this repo)

| Step | Module | Work |
|------|--------|------|
| 1 | `config/virtual_agents.json` | Ship six Cisco demo agents |
| 2 | `src/byova/catalog.py` | Load, coerce id→string, validate, map to SDK models |
| 3 | `src/config/settings.py` | `virtual_agents_config_path` from `WEBEX_VIRTUAL_AGENTS_CONFIG` |
| 4 | `src/byova/server.py` | Build `MediaServerConfig` with catalog |
| 5 | `src/byova/handlers.py` | `@server.on("list_virtual_agents")` → INFO console log per user request |
| 6 | `src/byova/handlers.py` | `session_start` → log `virtual_agent_id`; warn if not in catalog |
| 7 | `src/common/logging.py` | Extend formatter/extras for discovery fields |
| 8 | `src/byova/lifecycle.py` | Log `Virtual agent catalog loaded: N agents from <path>` at INFO |
| 9 | Tests + docs | Unit validation tests; quickstart Scenario 2 for console log |

### Discovery logging contract (user-requested)

Every `ListVirtualAgents` invocation MUST produce exactly one INFO log line on stdout:

**Plain console** (`LOG_JSON=false`):

```text
Flow Designer requested virtual agent list — org=<customer_org_id|n/a> agents=<N> tracking_id=<trackingid|n/a>
```

**JSON console** (`LOG_JSON=true`):

```json
{
  "level": "INFO",
  "operation": "list_virtual_agents",
  "outcome": "success",
  "org_id": "<customer_org_id>",
  "agent_count": 6,
  "tracking_id": "<trackingid>",
  "message": "Flow Designer requested virtual agent list"
}
```

Optional follow-up DEBUG line with full `agent_names` list is acceptable but MUST NOT replace the INFO summary line.

### Dependency note

`requirements.txt` MUST bump to `webex-byova[media]>=0.3.0` once SDK release is published. Until then, implementation is blocked on SDK catalog API (documented in research R3).

## Phase 2: Task Generation

Run `/speckit-tasks` to produce `tasks.md` with ordered implementation tasks (SDK release → app wiring → tests → quickstart validation).
