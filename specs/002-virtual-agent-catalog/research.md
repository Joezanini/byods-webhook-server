# Research: Virtual Agent Catalog for Flow Designer

**Feature**: `002-virtual-agent-catalog` | **Date**: 2026-06-08

## R1: How Flow Designer discovers virtual agents

**Decision**: Flow Designer (via WxCC) calls the gRPC `ListVirtualAgents` RPC on the registered BYOVA data-source endpoint—the same host/port as `ProcessCallerInput`.

**Rationale**: Confirmed by Cisco's [BYOVA gRPC Python simulator](https://github.com/CiscoDevNet/webex-contact-center-provider-sample-code/blob/main/bring-your-own/virtual-agent/grpc-interface/simulators/byova-grpc-python/code/src/server/AIAgentServer.py) (`ListVirtualAgents` handler) and the [webex-byova-gateway-python](https://github.com/webex/webex-byova-gateway-python) reference (`grpcurl ... VoiceVirtualAgent/ListVirtualAgents`).

**Alternatives considered**:
- HTTP REST catalog endpoint — rejected; WxCC BYOVA contract is gRPC-only for agent discovery.
- Control Hub static configuration — rejected; provider must advertise agents dynamically from the virtual agent server.

---

## R2: Reference catalog format

**Decision**: Use JSON array matching Cisco `virtual_agents.json`: `virtual_agent_id` (int or string in file, exposed as string in gRPC), `virtual_agent_name`, `is_default` (boolean).

**Rationale**: Direct compatibility with Cisco sample; operators can copy/paste the reference file.

**Alternatives considered**:
- YAML catalog — rejected; no reference in WxCC samples; JSON is sufficient for v1.
- Environment-variable-only list — rejected; does not scale beyond a few agents and is harder to validate.

---

## R3: SDK integration strategy (constitution-compliant)

**Decision**: Extend `webex-byova` SDK (target `>=0.3.0`) with:
1. `VirtualAgentConfig` model and `virtual_agents: list[VirtualAgentConfig]` on `MediaServerConfig` (loadable from env path or passed programmatically).
2. `VoiceVirtualAgentService.ListVirtualAgents` returns configured agents instead of empty `ListVAResponse`.
3. New media event `list_virtual_agents` with `ListVirtualAgentsEvent` (customer_org_id, is_default_virtual_agent_enabled, agent_count, tracking_id from gRPC metadata) dispatched before the response is returned.
4. `SessionStartEvent.metadata` enriched with `virtual_agent_id` and `customer_org_id` from the inbound `VoiceVARequest` (P3).

**Rationale**: SDK v0.2.0 implements `ListVirtualAgents` but returns an empty list with no configuration hook. Constitution prohibits custom gRPC servicers or proto vendoring in this repository.

**Alternatives considered**:
- Monkey-patch `VoiceVirtualAgentService` in this repo — rejected; fragile, breaks on SDK upgrades, violates SDK-First principle.
- Fork/register a parallel gRPC servicer — rejected; duplicate protocol implementation.
- Wait for Flow Designer to use HTTP — rejected; no evidence of alternate discovery path.

**Current blocker**: This feature requires a minimal SDK release before application wiring can be completed. Application code in this repo loads JSON and passes `virtual_agents` into `MediaServerConfig` at server construction.

---

## R4: Console-level discovery logging (user request)

**Decision**: Log every `ListVirtualAgents` call at **INFO** to stdout via the existing `StreamHandler`, using:
- **Plain console** (`LOG_JSON=false`): single human-readable line, e.g. `Flow Designer requested virtual agent list — org=<id> agents=6 tracking_id=<id>`
- **JSON console** (`LOG_JSON=true`, default): structured line with `operation=list_virtual_agents`, `outcome=success`, `customer_org_id`, `agent_count`, `tracking_id`, and `agent_names` summary

**Rationale**: User explicitly requested console visibility when Flow Designer reaches out. INFO ensures lines appear in default `uvicorn`/Docker logs without enabling DEBUG. Reuses `src/common/logging.log_event` pattern from feature `001`.

**Alternatives considered**:
- DEBUG-only logging — rejected; invisible in default operator consoles.
- Separate log file — rejected; unnecessary for v1; stdout is standard for container/VPS deploys.
- Logging only in SDK without app hook — rejected; app layer should own message wording and field selection for operator clarity.

**Implementation hook**: Application registers `@media.on("list_virtual_agents")` handler in `src/byova/handlers.py` (or dedicated `discovery.py`) after SDK dispatches the event.

---

## R5: Catalog validation and startup behavior

**Decision**: Validate catalog at application startup before `media.start()`:
- Reject duplicate `virtual_agent_id` values
- Reject more than one `is_default: true`
- Reject empty catalog (zero agents) with fail-fast `MediaConfigError`
- Reject missing/unreadable config file with actionable stderr message

**Rationale**: Matches spec FR-004, FR-005, FR-009; prevents silent empty-list regressions.

**Alternatives considered**:
- Lazy validation on first ListVirtualAgents call — rejected; fails later and harder to diagnose in Flow Designer.
- Allow empty catalog with warning — rejected; contradicts SC-001 and spec FR-009 intent.

---

## R6: Session agent identifier (P3)

**Decision**: Surface `virtual_agent_id` from `VoiceVARequest` in `SessionStartEvent.metadata` via SDK enhancement; application logs it at INFO on `session_start` and warns if ID is not in the loaded catalog.

**Rationale**: Proto includes `virtual_agent_id` on `VoiceVARequest`; SDK currently does not forward it to handlers. Cisco simulator routes by this field.

**Alternatives considered**:
- Parse only from SESSION_START event parameters — rejected; WxCC sends `virtual_agent_id` on the request envelope per proto, not only in event parameters.

---

## R7: Configuration path

**Decision**: `WEBEX_VIRTUAL_AGENTS_CONFIG` env var, default `config/virtual_agents.json` relative to repo root (or process working directory in Docker).

**Rationale**: Mirrors Cisco sample layout; operators override path per environment without code changes.

**Alternatives considered**:
- Hard-coded path only — rejected; breaks Docker mounts and multi-env deploys.
- Embed sample in Python module — rejected; prevents operator edits without redeploy.
