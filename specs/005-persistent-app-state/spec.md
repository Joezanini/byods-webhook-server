# Feature Specification: Persistent Application State

**Feature Branch**: `005-persistent-app-state`

**Created**: 2026-06-13

**Status**: Draft

**Input**: User description: "Add persistent storage for application state so authorized customer orgs and configuration survive server restarts and multi-instance deployments. Durable org authorization state, managed virtual agent catalog, and optional operational audit. Integration refresh tokens remain in environment/secrets."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Durable Org Authorization State (Priority: P1)

As an integration operator managing multiple authorized WxCC customer orgs, when a customer org has authorized my service app, org-scoped credentials and authorization status remain available after the server restarts so BYODS CLI operations and BYOVA media can continue without requiring the customer to re-authorize in Control Hub.

**Why this priority**: Today, authorized org credentials live only in memory. Every restart forces operators to wait for a new authorization webhook before BYODS or BYOVA can serve that org. This is the highest-impact reliability gap blocking production multi-org operation.

**Independent Test**: Authorize one or more test orgs via the existing service app webhook flow, restart the server (or simulate a cold start), then perform a BYODS read operation for each previously authorized org without sending a new Control Hub authorization. All orgs should succeed.

**Acceptance Scenarios**:

1. **Given** a customer org has completed service app authorization via webhook, **When** the server persists org state and later restarts, **Then** BYODS read operations for that org succeed using stored org-scoped credentials without a new Control Hub authorization.
2. **Given** a customer org receives a deauthorization webhook, **When** the event is processed, **Then** persisted credentials for that org are removed within the same webhook handling cycle and subsequent BYODS/BYOVA operations for that org are rejected.
3. **Given** multiple authorized orgs in the same deployment, **When** an operator or automated process reads org-scoped data, **Then** only credentials and metadata for the requested org are returned—never another org's tokens or status.
4. **Given** a duplicate authorized webhook for an org already in authorized state, **When** the event is processed, **Then** the outcome is idempotent with no duplicate side effects (no duplicate credential records or spurious data source registrations beyond existing behavior).
5. **Given** the existing POST /webhooks/webex authorization and deauthorization flows, **When** an operator triggers them from Control Hub, **Then** observable webhook behavior (acknowledgment, logging themes, operator-facing outcomes) is unchanged from today's experience.

---

### User Story 2 - Managed Virtual Agent Catalog (Priority: P2)

As a voice virtual agent developer, I can define and update virtual agents (identifier, display name, optional default flag) through a durable store instead of editing a local JSON file, so Flow Designer discovery stays consistent across restarts and replicas without redeploying configuration files.

**Why this priority**: Feature 002 established catalog semantics and Flow Designer discovery, but file-based configuration requires process restarts and does not scale to multi-instance deployments. Durable catalog storage unlocks operational agility and horizontal scaling.

**Independent Test**: Seed or create a catalog with at least two agents via the supported management path, confirm Flow Designer discovery returns them, update one agent's display name, confirm the new name appears on the next discovery request without editing source files or redeploying a config artifact.

**Acceptance Scenarios**:

1. **Given** a valid catalog with at least one virtual agent entry, **When** Flow Designer (or WxCC on its behalf) requests the virtual agent list, **Then** all persisted entries are returned with identifier, display name, and default flag consistent with feature 002 semantics.
2. **Given** an operator adds a new agent with a unique identifier and display name, **When** discovery runs after the change is persisted, **Then** the new agent appears in the list.
3. **Given** an operator updates an agent's display name, **When** discovery runs after the change is persisted, **Then** Flow Designer shows the updated name without requiring a file edit or application redeploy for configuration alone.
4. **Given** a catalog validation rule is violated (zero agents, duplicate identifiers, or more than one default), **When** an operator attempts to save the catalog, **Then** the change is rejected with a clear, operator-facing error explaining the constraint.
5. **Given** two or more server instances share the same durable store, **When** an operator updates the catalog on one instance, **Then** all instances eventually serve the updated catalog on discovery requests (eventual consistency acceptable in v1 if documented for operators).

---

### User Story 3 - Operational Audit of Service App Lifecycle (Priority: P3)

As an integration operator, I can review recent service app lifecycle events (org, event type, timestamp, outcome) for troubleshooting and idempotency visibility. This is audit and observability only—not required for core call flow.

**Why this priority**: Structured logs already capture webhook activity, but a queryable recent history helps operators diagnose duplicate deliveries, failed side effects, and org-specific authorization timelines without parsing raw log streams.

**Independent Test**: Trigger authorize and deauthorize webhooks for a test org, then retrieve the recent audit view and confirm each event appears with org identifier, event type, timestamp, and success/failure outcome. Verify audit records contain no secret values.

**Acceptance Scenarios**:

1. **Given** a successful authorization webhook is processed, **When** an operator reviews recent lifecycle events, **Then** an audit record exists with org identifier, event type (authorized), timestamp, and success outcome.
2. **Given** a deauthorization webhook is processed, **When** an operator reviews recent lifecycle events, **Then** an audit record exists with org identifier, event type (deauthorized), timestamp, and success outcome.
3. **Given** a webhook fails validation or processing, **When** an operator reviews recent lifecycle events, **Then** a record exists (or a log-equivalent entry is available) with failure outcome and enough context to troubleshoot—without access tokens or refresh tokens in the record.
4. **Given** audit data exceeds the configured retention window, **When** older events age out, **Then** core authorization and catalog behavior is unaffected.

---

### Edge Cases

- What happens when the durable store is unavailable at startup? The server should fail readiness (not accept traffic that depends on missing org or catalog state) or operate in a documented degraded mode with explicit operator warnings—never silently serve stale or cross-org data.
- What happens when the server restarts and persisted org tokens are expired? Org authorization status remains, but token refresh behavior follows existing SDK patterns; failures are logged with org context and do not expose secrets.
- What happens when a deauthorization webhook arrives for an org that was never authorized or was already deauthorized? Processing completes idempotently with no credential leakage and a clear logged outcome.
- What happens under high webhook retry volume for the same org? Duplicate authorized events produce no duplicate credential records or spurious registrations beyond current idempotency guarantees.
- What happens when two operators or instances attempt concurrent catalog updates? Last-write-wins or conflict rejection applies consistently; invalid intermediate states are never exposed to Flow Designer discovery.
- What happens when an agent referenced by an existing IVR flow is removed from the catalog? Discovery no longer lists the agent; live sessions follow existing feature 002 fallback behavior for unknown agent identifiers.
- What happens when persisted data for one org is corrupted or partially written? Reads for that org fail safely with operator-facing errors; other orgs remain unaffected.

## Requirements *(mandatory)*

### Functional Requirements

#### Org authorization persistence (P1)

- **FR-001**: System MUST persist customer organization authorization state including org identifier, authorization status, and authorization/deauthorization timestamps for each org that completes the service app webhook lifecycle.
- **FR-002**: System MUST persist org-scoped service app credentials (access token, optional refresh token, expiry metadata) per authorized org and MUST protect them at rest using encryption or an equivalent managed secret mechanism—not plain text in application logs, git, or operator-visible audit output.
- **FR-003**: System MUST load persisted authorized org credentials on startup so BYODS and BYOVA operations for previously authorized orgs succeed without requiring a new Control Hub authorization event.
- **FR-004**: System MUST remove persisted org credentials and mark the org deauthorized when a valid deauthorization webhook is processed, within the same webhook handling cycle.
- **FR-005**: System MUST enforce strict org isolation on all persistence-backed reads and writes so credentials, authorization metadata, and audit records for one org are never returned or modified when acting on behalf of another org.
- **FR-006**: System MUST preserve existing POST /webhooks/webex authorization and deauthorization behavior from the operator's perspective, integrating persistence alongside current webhook handling rather than replacing the flow.
- **FR-007**: System MUST handle duplicate authorization webhooks idempotently without creating duplicate credential records or corrupting org state.
- **FR-008**: System MUST NOT persist integration-level OAuth client secrets or the integration refresh token in application org/catalog tables; those remain in environment variables or managed secrets only.

#### Virtual agent catalog persistence (P2)

- **FR-009**: System MUST persist virtual agent catalog entries with stable agent identifier, human-readable display name, and optional default flag, replacing file-based catalog as the source of truth for discovery.
- **FR-010**: System MUST return the persisted catalog when Flow Designer (or WxCC) requests the virtual agent list, preserving feature 002 discovery semantics.
- **FR-011**: System MUST require at least one catalog entry at all times; attempts to persist an empty catalog MUST be rejected.
- **FR-012**: System MUST enforce unique agent identifiers within the catalog; duplicate identifiers MUST be rejected with a clear operator-facing error.
- **FR-013**: System MUST allow at most one default agent; attempts to persist more than one default MUST be rejected with a clear operator-facing error.
- **FR-014**: System MUST allow operators to add, update, and remove catalog entries through a supported management mechanism without editing application source or redeploying static configuration files.
- **FR-015**: System MUST validate catalog state before persisting changes and MUST reject invalid states with actionable error messages.

#### Operational audit (P3)

- **FR-016**: System SHOULD record recent service app lifecycle events including org identifier, event type (authorized, deauthorized, or processing failure), timestamp, and outcome (success or failure).
- **FR-017**: Audit records MUST NOT contain access tokens, refresh tokens, or other secret material.
- **FR-018**: System SHOULD make recent audit records retrievable by operators for troubleshooting without requiring direct access to raw infrastructure logs.

#### Cross-cutting

- **FR-019**: System MUST continue structured logging for webhooks, CRUD, and media events with org identifier and operation context, maintaining the project's no-secret-leakage logging standard.
- **FR-020**: System MUST NOT persist active BYOVA media session state (conversation turns, audio buffers, or other ephemeral call context); media session handling remains in-memory for the life of the call.
- **FR-021**: System MUST NOT use durable storage as the system of record for BYODS data source records; WxCC API remains authoritative for data source entities in v1.

### Key Entities *(include if feature involves data)*

- **Customer Organization**: A WxCC customer org identified by org identifier. Tracks authorization state (authorized or deauthorized), when authorization occurred, and when deauthorization occurred (if applicable). One organization has at most one active credential set at a time.
- **Service App Credentials (per org)**: Org-scoped access token, optional refresh token, and expiry metadata tied to exactly one customer organization. Must be protected at rest. Removed when the org is deauthorized.
- **Virtual Agent Catalog Entry**: A discoverable virtual agent with stable identifier, display name, and optional default flag. The full catalog must contain at least one entry, unique identifiers, and at most one default.
- **Service App Lifecycle Audit Event** *(optional, P3)*: A historical record of a webhook lifecycle processing attempt with org identifier, event type, timestamp, and outcome—excluding secret values.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After a server restart, 100% of previously authorized test orgs can complete BYODS read operations without a new Control Hub authorization event.
- **SC-002**: Operators can update a virtual agent display name and see the revised name in Flow Designer discovery within one operational cycle (no configuration file edit and no redeploy required solely for the name change).
- **SC-003**: During multi-org testing, zero instances of cross-org credential or metadata exposure occur in persistence-backed reads.
- **SC-004**: Deauthorization webhooks remove persisted org credentials within one webhook handling cycle; subsequent BYODS/BYOVA attempts for that org fail authorization checks 100% of the time in test scenarios.
- **SC-005**: Invalid catalog states (empty catalog, duplicate agent identifiers, multiple defaults) are rejected 100% of the time with operator-understandable error messages in validation tests.
- **SC-006**: Audit and log output for lifecycle events contain zero plaintext org access or refresh tokens in security review sampling.

## Assumptions

- A single deployment serves multiple customer orgs; org isolation is mandatory.
- Operators prefer a managed cloud database with a generous free tier for v1 cost control; exact product selection is deferred to planning.
- Integration refresh tokens and OAuth client secrets remain in environment variables or managed secrets—the durable store holds org-scoped service app tokens only.
- Virtual agent catalog updates may propagate to all running instances with eventual consistency in v1; operators are informed if discovery may lag briefly after a change.
- Webhook idempotency requirements from feature 001 remain in force; persistence must not weaken duplicate-event handling.
- Feature 001 webhook + BYODS/BYOVA behavior and feature 002 virtual agent catalog semantics are the behavioral baseline; this feature adds durability without changing Webex-facing contracts.
- Active BYOVA media session state, BYODS data source system-of-record responsibilities, and CI/CD pipeline metadata (feature 004) remain out of scope.
- Audit retention defaults to a practical troubleshooting window (approximately 30 days) unless operators configure otherwise during planning.

## Constitution Alignment *(mandatory for BYODS Webhook Server)*

Verify this spec complies with `.specify/memory/constitution.md`:

- **SDK-First**: Webex token refresh and BYODS/BYOVA operations continue to delegate to the `webex-byova` SDK; persistence stores state the SDK consumes—it does not reimplement Webex protocols.
- **Webhook Integrity**: Existing POST /webhooks/webex flow is preserved; persistence integrates alongside current authorization/deauthorization handling. No rewrite is authorized.
- **Modular boundaries**: Org credential persistence aligns with the webhook service boundary; catalog persistence aligns with BYOVA/media discovery; shared storage access lives in a common layer without leaking persistence details across modules.
- **Production ops**: Readiness must reflect durable-store availability; structured logging and health checks remain required; configuration for storage connectivity is environment-driven.
- **Security**: Org-scoped tokens encrypted or stored via managed secrets at rest; deauthorization revokes persisted access; audit and logs exclude secrets; org isolation enforced on all reads.
- **Delivery order**: This feature builds on completed auth/webhook (001) and catalog semantics (002); persistence is an incremental reliability layer, not a replacement for SDK-backed auth flows.
