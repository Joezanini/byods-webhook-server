# Feature Specification: Virtual Agent Catalog for Flow Designer

**Feature Branch**: `002-virtual-agent-catalog`

**Created**: 2026-06-08

**Status**: Draft

**Input**: User description: "Webex Contact Center Flow Designer requires the Virtual Agent server to provide a list of available Virtual Agents for IVR configuration. Configure a sample list modeled on the Cisco BYOVA gRPC Python simulator virtual_agents.json, using the webex-byova SDK where possible."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Discover Virtual Agents in Flow Designer (Priority: P1)

As a contact center administrator configuring an IVR flow in Webex Contact Center Flow Designer, when I add or configure a Virtual Agent activity and connect it to my registered Bring Your Own Virtual Agent provider, I see a populated list of available virtual agents (each with a human-readable name) so that I can select which agent handles caller interactions in that flow step.

**Why this priority**: Without a discoverable agent catalog, Flow Designer cannot complete IVR configuration. This is the blocking gap the user observed—the media server may be running, but the designer shows no agents to choose from.

**Independent Test**: With the virtual agent server running and a data source registered in Control Hub, open Flow Designer (or invoke the equivalent agent-discovery call against the registered endpoint) and confirm at least one named virtual agent appears in the selection list.

**Acceptance Scenarios**:

1. **Given** a running virtual agent server with a configured catalog of agents, **When** Flow Designer requests the available agent list from the registered provider endpoint, **Then** the response includes every configured agent with its display name and identifier.
2. **Given** a catalog entry marked as the default agent, **When** Flow Designer requests the agent list, **Then** that entry is indicated as the default option.
3. **Given** the sample demonstration catalog (Travel Booking Agent, Credit card service, Insurance service, Barge-in Travel Booking Agent, Scripted Agent, Barge-in General Agent), **When** the server starts with default sample configuration, **Then** all six agents are discoverable by Flow Designer without additional setup.
4. **Given** a registered data source pointing at the virtual agent endpoint, **When** an administrator opens Virtual Agent configuration in Flow Designer, **Then** agent names match the configured catalog entries (not an empty list).

---

### User Story 2 - Operator-Managed Agent Catalog (Priority: P2)

As an integration operator, I can define and update the virtual agents my server advertises—adding, renaming, or removing entries and designating a default—without modifying application source code, so that I can tailor the Flow Designer experience for each deployment or demo environment.

**Why this priority**: A hard-coded agent list is sufficient for a quick demo but not for real operator workflows. External configuration keeps the catalog maintainable across environments.

**Independent Test**: Change the catalog configuration, restart the server, and verify Flow Designer reflects the updated agent names and count without redeploying code.

**Acceptance Scenarios**:

1. **Given** a valid catalog configuration file, **When** the server starts, **Then** it loads all entries and makes them available for discovery.
2. **Given** an updated catalog configuration, **When** the server is restarted, **Then** Flow Designer sees the revised agent list on the next discovery request.
3. **Given** a catalog entry is removed, **When** discovery runs after restart, **Then** that agent no longer appears in Flow Designer.
4. **Given** an operator adds a new agent with a unique identifier and display name, **When** discovery runs, **Then** the new agent appears alongside existing entries.

---

### User Story 3 - Agent Selection Carried Into Live Calls (Priority: P3)

As a voice virtual agent developer, when a caller reaches an IVR step configured with a specific virtual agent from the catalog, the server receives the selected agent identifier at session start so that downstream conversation logic can route or behave differently per agent.

**Why this priority**: Discovery alone enables Flow Designer setup, but the selected agent must be meaningful during live calls. The Cisco reference simulator routes `ProcessCallerInput` by `virtual_agent_id`; this story ensures end-to-end coherence between catalog and runtime.

**Independent Test**: Configure a flow to use a specific catalog agent, place a test call, and verify the server logs or handles the session with the matching agent identifier.

**Acceptance Scenarios**:

1. **Given** a flow configured to use agent "Travel Booking Agent" (identifier `1`), **When** a call session starts, **Then** the server associates the session with agent identifier `1`.
2. **Given** two flows using different catalog agents, **When** concurrent calls arrive, **Then** each session carries the correct agent identifier independently.
3. **Given** a session starts with an agent identifier not present in the catalog, **When** media processing begins, **Then** the server logs a clear warning and applies a documented fallback behavior (e.g., default agent or graceful session handling) without crashing.

---

### Edge Cases

- What happens when the catalog configuration file is missing, unreadable, or contains invalid structure at startup?
- How does the system respond when the catalog is empty (zero agents defined)?
- What happens when multiple entries are marked `is_default: true`?
- What happens when two entries share the same agent identifier?
- What happens when Flow Designer requests the agent list while the media service is disabled or unreachable?
- What happens when an agent display name contains special characters or exceeds reasonable length for UI display?
- What happens when a catalog agent is removed but existing IVR flows still reference its identifier?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The virtual agent server MUST expose a discoverable catalog of virtual agents to Webex Contact Center Flow Designer via the provider's standard agent-listing capability (the same mechanism WxCC uses when populating the Virtual Agent picker in IVR flows).
- **FR-002**: Each catalog entry MUST include a stable agent identifier, a human-readable display name, and an optional default flag.
- **FR-003**: The server MUST return all configured catalog entries when Flow Designer (or WxCC on its behalf) requests the agent list.
- **FR-004**: Agent identifiers MUST be unique within a single catalog; duplicate identifiers MUST be rejected at startup with a clear error.
- **FR-005**: At most one catalog entry MAY be marked as the default agent; if multiple defaults are configured, the server MUST reject startup with a clear validation error.
- **FR-006**: The server MUST ship with a sample catalog containing six demonstration agents aligned with the Cisco BYOVA gRPC Python simulator reference: Travel Booking Agent, Credit card service, Insurance service, Barge-in Travel Booking Agent, Scripted Agent, and Barge-in General Agent.
- **FR-007**: Operators MUST be able to customize the catalog through external configuration (not source-code edits) and see changes after server restart.
- **FR-008**: When a call session begins, the server MUST make the Flow Designer–selected agent identifier available to conversation handlers for routing or logging.
- **FR-009**: If the catalog configuration is missing or invalid at startup, the server MUST fail fast with an actionable error message rather than silently advertising an empty or partial list.
- **FR-010**: If the media service is disabled, agent discovery MUST NOT be advertised on endpoints that are not running; operators MUST receive clear documentation that both data-source registration and a running media endpoint are required for Flow Designer integration.
- **FR-011**: Catalog changes MUST NOT require changes to the existing serviceApp webhook authorization flow or BYODS data-source registration behavior established in feature `001-byods-byova-spec`.

### Key Entities

- **Virtual Agent Catalog Entry**: A provider-defined agent offered for IVR configuration. Attributes: agent identifier (stable string or numeric value exposed as string), display name, default flag (boolean), optional extended attributes for future use.
- **Agent Discovery Response**: The set of catalog entries returned when WxCC/Flow Designer queries the provider for available agents. Must be complete, ordered consistently, and suitable for UI display.
- **Session Agent Context**: The agent identifier selected in the IVR flow and attached to an active caller session, linking Flow Designer configuration to runtime behavior.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Administrators configuring an IVR flow see at least one named virtual agent in Flow Designer within 30 seconds of completing data-source registration and server startup (no empty-list state when catalog is valid).
- **SC-002**: 100% of valid catalog entries appear in discovery responses—no agents are silently omitted.
- **SC-003**: Operators can add or rename a catalog entry and see the change reflected in Flow Designer after a single server restart, without code changes.
- **SC-004**: In test calls, the agent identifier selected in the flow matches the identifier recorded at session start in 100% of successful media sessions.
- **SC-005**: Invalid catalog configurations (duplicates, multiple defaults, malformed structure) are detected at startup in 100% of cases, with error messages sufficient for an operator to correct the file without developer assistance.
- **SC-006**: The sample six-agent catalog enables a complete Flow Designer → test call demo path without custom agent definitions.

## Assumptions

- Flow Designer discovers agents by querying the same registered BYOVA data-source endpoint used for live media, via WxCC's standard virtual-agent listing protocol (as demonstrated in Cisco's BYOVA gRPC Python simulator and the Webex BYOVA gateway reference implementations).
- The Cisco [`virtual_agents.json`](https://github.com/CiscoDevNet/webex-contact-center-provider-sample-code/blob/main/bring-your-own/virtual-agent/grpc-interface/simulators/byova-grpc-python/code/src/config/virtual_agents.json) structure (`virtual_agent_id`, `virtual_agent_name`, `is_default`) is the reference format for external catalog configuration.
- A single shared catalog serves all authorized customer orgs in v1; per-org agent lists are out of scope unless a future spec extends this feature.
- Catalog hot-reload without restart is out of scope for v1; restart after configuration change is acceptable.
- Implementation will delegate protocol handling to the `webex-byova` SDK per project constitution; if the SDK's agent-listing hook currently returns an empty catalog by default, a minimal SDK or application configuration extension is an expected planning outcome—not a custom protocol reimplementation.
- Extended per-agent attributes beyond id, name, and default flag are out of scope unless required by WxCC discovery contract.
- Removing a catalog agent does not automatically update existing IVR flows; administrators are responsible for re-pointing flows to valid agents.

## Constitution Alignment *(mandatory for BYODS Webhook Server)*

Verify this spec complies with `.specify/memory/constitution.md`:

- **SDK-First**: Agent listing and media sessions MUST use `webex-byova` SDK capabilities (`ListVirtualAgents` and existing `BYOVAMediaServer` lifecycle). No custom gRPC servicer or proto vendoring in this repository.
- **Webhook Integrity**: Existing `POST /webhooks/webex` authorization/deauthorization behavior remains unchanged (FR-011).
- **Modular boundaries**: Catalog loading and registration belong in the BYOVA media module; shared configuration utilities may live in `src/config/` without coupling to webhook or BYODS CRUD modules.
- **Production ops**: Startup validation errors, structured logging of catalog load outcome and session agent identifiers, and environment-driven catalog path configuration are required in the implementation plan.
- **Security**: Agent listing inherits existing media endpoint token verification settings; no new unauthenticated admin surface is introduced.
- **Delivery order**: Catalog configuration layout → SDK integration for agent listing → session agent context → sample catalog and quickstart documentation → integration verification with Flow Designer or `ListVirtualAgents` probe.
