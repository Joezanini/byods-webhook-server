# Feature Specification: BYODS CRUD & BYOVA Media Platform

**Feature Branch**: `001-byods-byova-spec`

**Created**: 2026-06-07

**Status**: Draft

**Input**: User description: "turn requirements into a formal spec (BYODS CRUD + BYOVA media as user stories)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Service App Lifecycle via Webhooks (Priority: P1)

As an integration operator, when a customer administrator authorizes or deauthorizes my Webex Contact Center service app, the server receives the lifecycle event, records the outcome, and keeps org-scoped access credentials available (or removes them on deauthorization) so that BYODS and BYOVA features can operate for that customer org.

**Why this priority**: Authorization is the prerequisite for every other capability. Without a reliable webhook path, data sources cannot be registered and media cannot flow. This flow is already validated in production and must remain the foundation.

**Independent Test**: Trigger authorize and deauthorize events from Webex Control Hub (or equivalent test harness) and verify the server acknowledges each event, logs org identity and event type, and reflects the correct credential state for subsequent operations.

**Acceptance Scenarios**:

1. **Given** a valid service app authorization event for a customer org, **When** the webhook is delivered, **Then** the server accepts the event, stores org-scoped credentials for that org, and returns a successful acknowledgment.
2. **Given** a valid deauthorization event for a previously authorized org, **When** the webhook is delivered, **Then** the server removes stored credentials for that org and returns a successful acknowledgment.
3. **Given** an invalid or unexpected webhook payload, **When** the server receives it, **Then** the request is rejected with a clear error response and no credential state is changed.
4. **Given** the server restarts after prior authorizations, **When** a new authorization webhook arrives, **When** integration credentials are configured, **Then** the server can still obtain org-scoped credentials without manual re-authorization of the developer integration.

---

### User Story 2 - BYODS Data Source Management (Priority: P2)

As an integration operator, I can create, view, update, and delete registered Bring Your Own Data Source (BYODS) entries for authorized customer orgs so that Webex Contact Center knows where to send call-related data (including audio routing metadata) for my voice virtual agent.

**Why this priority**: Data source registration is required before WxCC can route media to the operator's endpoint. CRUD gives operators full lifecycle control beyond the automatic registration performed on authorization.

**Independent Test**: With a test org already authorized via webhooks, perform create → read → update → delete on a data source and confirm each operation is reflected when listing or fetching that data source. Verify duplicate registration for the same endpoint URL is handled safely.

**Acceptance Scenarios**:

1. **Given** an authorized customer org, **When** the operator registers a new data source with a valid schema, public endpoint URL, audience, subject, and token lifetime, **Then** the data source is created and its status is visible to the operator.
2. **Given** an existing data source for an org, **When** the operator requests its details, **Then** the server returns the current configuration including URL, schema association, and operational status.
3. **Given** an existing data source, **When** the operator updates allowed fields (such as URL, token lifetime, or subject), **Then** the changes persist and are visible on subsequent reads.
4. **Given** an existing data source no longer needed, **When** the operator deletes it, **Then** it is removed and no longer appears in listings for that org.
5. **Given** a data source URL already registered for an org, **When** the operator attempts to create another with the same URL, **Then** the server does not create a duplicate and reports that the URL is already registered.
6. **Given** an unauthorized or unknown org identifier, **When** the operator attempts any CRUD operation, **Then** the request is rejected without exposing other orgs' data.

---

### User Story 3 - BYOVA Real-Time Media Sessions (Priority: P3)

As a voice virtual agent developer, when Webex Contact Center routes call audio to my registered data source endpoint, the server accepts bidirectional media streams, can inspect or transform audio in real time if needed, and can send audio responses back so that virtual agent conversations proceed without perceptible interruption.

**Why this priority**: Media streaming is the customer-visible outcome of the integration. It depends on authorization (P1) and data source registration (P2) but delivers the core BYOVA value.

**Independent Test**: With a registered data source pointing at the server's media endpoint, place a test call through WxCC and verify the server establishes a media session, receives inbound audio, and can send outbound audio for the duration of the call.

**Acceptance Scenarios**:

1. **Given** a registered data source whose URL matches the server's media endpoint, **When** WxCC initiates a call session, **Then** the server accepts the connection and begins receiving inbound audio within 5 seconds of session start.
2. **Given** an active media session, **When** inbound audio arrives, **Then** the server can process or pass through audio and send outbound audio responses in the same session.
3. **Given** an active media session, **When** the call ends or WxCC closes the session, **Then** the server releases session resources and logs session completion with org and session identifiers.
4. **Given** a connection attempt with invalid or expired credentials, **When** media setup is requested, **Then** the server rejects the session without exposing internal configuration.
5. **Given** multiple concurrent calls for the same org, **When** sessions overlap, **Then** each session is handled independently without cross-session audio leakage.

---

### User Story 4 - Production Operations & Security (Priority: P4)

As an operator deploying this server to production (container, VPS, or managed platform), I can confirm service health, diagnose failures from structured logs, configure secrets and feature behavior via environment settings, and trust that customer-facing endpoints enforce appropriate access controls.

**Why this priority**: Production reliability and security are cross-cutting concerns that make P1–P3 operable in customer orgs. They can be validated independently via health checks and security tests without a live WxCC call.

**Independent Test**: Deploy or run the server with production-like configuration, hit the health endpoint, trigger a sample CRUD and webhook operation, and verify logs contain org ID, operation type, and outcome without leaking secrets.

**Acceptance Scenarios**:

1. **Given** a running server instance, **When** an operator checks the health endpoint, **Then** the server reports healthy status suitable for load balancer or platform health probes.
2. **Given** any inbound webhook, CRUD action, or media session event, **When** processing completes (success or failure), **Then** a structured log entry is emitted with org identifier, operation type, and outcome.
3. **Given** protected operator or media endpoints, **When** a request lacks valid credentials, **Then** access is denied.
4. **Given** secrets and connection settings, **When** the server starts, **Then** all sensitive values are loaded from environment configuration only—never from source control.
5. **Given** deployment to a container environment, **When** the image is built and started with documented environment variables, **Then** the server reaches healthy state without manual code changes.

---

### Edge Cases

- What happens when the server restarts and in-memory org tokens are lost? Authorized orgs remain authorized in Webex, but the server must re-bootstrap developer integration credentials and re-fetch org tokens on the next authorized webhook or operation.
- What happens when automatic data source registration on authorization fails (invalid URL, schema mismatch, network error)? The webhook acknowledgment still succeeds; the failure is logged with actionable context and the operator can register manually via CRUD.
- What happens when a data source URL does not exactly match the media endpoint WxCC uses? Media sessions fail to establish; CRUD read operations help operators verify URL alignment before go-live.
- What happens under high webhook retry volume? Duplicate authorization events for the same org are handled idempotently without duplicate data sources or credential corruption.
- What happens when media sessions idle or stall? Sessions time out gracefully with logged reason; resources are released.
- What happens when rate limits are exceeded on public endpoints? Requests are throttled with appropriate responses without affecting already-established media sessions.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST receive and process service app `authorized` and `deauthorized` webhook events without breaking existing production behavior.
- **FR-002**: System MUST maintain org-scoped service app credentials in memory for authorized orgs and remove them on deauthorization.
- **FR-003**: System MUST optionally auto-register a BYODS data source when an org is authorized, using operator-configured endpoint URL, schema, audience, subject, and token lifetime settings.
- **FR-004**: System MUST allow operators to create a new data source for an authorized org with validated schema, URL, audience, subject, and token lifetime.
- **FR-005**: System MUST allow operators to list and retrieve data sources for an authorized org.
- **FR-006**: System MUST allow operators to update mutable data source properties for an authorized org.
- **FR-007**: System MUST allow operators to delete a data source for an authorized org.
- **FR-008**: System MUST prevent duplicate data source registration for the same URL within an org.
- **FR-009**: System MUST reject BYODS operations for orgs that are not authorized or not found.
- **FR-010**: System MUST expose a media endpoint at the URL registered in the data source so WxCC can establish sessions.
- **FR-011**: System MUST support bidirectional real-time audio streaming for active call sessions.
- **FR-012**: System MUST isolate concurrent media sessions so audio and state do not leak between calls or orgs.
- **FR-013**: System MUST validate access credentials on protected operator and media endpoints per Webex BYOVA/BYODS security guidance.
- **FR-014**: System MUST provide a health check endpoint for deployment platforms and operators.
- **FR-015**: System MUST emit structured logs for webhooks, CRUD operations, and media session lifecycle events including org identifier and outcome.
- **FR-016**: System MUST load all secrets and environment-specific settings from external configuration, not from the repository.
- **FR-017**: System MUST handle webhook, CRUD, and media I/O concurrently without blocking the health endpoint.
- **FR-018**: System MUST return clear, non-leaking error responses when validation or authentication fails.
- **FR-019**: System MUST support schema association when creating or updating data sources so WxCC understands the data format expected at the endpoint.
- **FR-020**: System MUST refresh or obtain valid tokens for BYODS operations using the official integration path rather than operator-managed manual token entry per request.

### Key Entities

- **Customer Organization**: A Webex Contact Center tenant identified by org ID; authorization state determines whether BYODS and BYOVA operations are permitted.
- **Service App Credentials**: Org-scoped access tokens obtained after authorization; required for data source and media operations on behalf of that org.
- **Data Source**: A registered BYODS entry linking a customer org to a public endpoint URL, schema, audience, subject, token lifetime, and operational status.
- **Data Source Schema**: The WxCC-defined format contract (e.g., call audio metadata) associated with a data source registration.
- **Media Session**: A real-time bidirectional audio connection between WxCC and the operator's endpoint for a single call, with start, active, and end states.
- **Integration Credentials**: Developer-level credentials used to bootstrap token exchange when customer orgs authorize the service app.
- **Webhook Event**: An inbound service app lifecycle notification (`authorized` or `deauthorized`) from Webex Contact Center.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 99% of valid service app webhook events are acknowledged successfully within 3 seconds under normal load.
- **SC-002**: Operators can complete a full data source CRUD cycle (create, read, update, delete) for a test org in under 10 minutes using documented procedures.
- **SC-003**: Media sessions begin receiving inbound audio within 5 seconds of WxCC session initiation in integration test environments.
- **SC-004**: Zero cross-org data exposure in CRUD listings and media sessions during concurrent multi-org testing.
- **SC-005**: 100% of failed webhook, CRUD, and media operations produce structured log entries sufficient for operators to identify org, operation, and failure reason without exposing secrets.
- **SC-006**: Health check endpoint returns success within 1 second when the server is running and integration credentials are valid.
- **SC-007**: Duplicate authorization webhooks for the same org do not create duplicate data sources for the same URL in 100% of test cases.
- **SC-008**: Operators can deploy a fresh instance using only documented environment configuration and reach healthy status without code modifications.

## Assumptions

- Target users are integration operators and voice virtual agent developers (Joe Zanini / Webex DevRel and similar), not end-customer administrators performing CRUD directly.
- Customer administrators continue to authorize the service app through Webex Control Hub; CRUD and media features operate on already-authorized orgs.
- The official Webex BYOVA/BYODS SDK encapsulates protocol details for auth, data source APIs, and recommended media transport; this spec does not prescribe custom protocol implementations.
- Primary media use case is voice (call audio) for BYOVA virtual agents; video or auxiliary channels are out of scope unless added in a future spec.
- Default data source schema and audience/subject values suitable for call audio virtual agent testing are acceptable starting defaults; operators can override via configuration.
- In-memory credential storage is acceptable for this phase; persistent token storage across restarts is out of scope unless specified later.
- Automatic data source registration on authorization (already present) remains enabled by default but can be disabled by operators who prefer manual CRUD only.
- The registered data source URL must exactly match the public media endpoint hostname and path approved in the service app configuration.
- Rate limiting and CORS apply to HTTP operator surfaces; media transport security follows Webex session credential validation.
- Reference patterns from the official BYOVA gateway example inform behavior but this service app maintains its own modular layout.

## Constitution Alignment *(mandatory for BYODS Webhook Server)*

Verify this spec complies with `.specify/memory/constitution.md`:

- Webex integration via `webex-byova` SDK (no custom protocol implementations) — **Aligned**: FR-020 and assumptions delegate auth, BYODS, and BYOVA to the SDK.
- Existing serviceApp webhook behavior unchanged unless this spec explicitly authorizes a rewrite — **Aligned**: FR-001 and User Story 1 preserve existing webhook flow; no rewrite authorized.
- Feature scope maps to webhook, BYODS CRUD, or BYOVA media module boundaries — **Aligned**: User Stories 1–3 map to webhook, BYODS CRUD, and BYOVA media respectively; User Story 4 covers cross-cutting production concerns.
- Security, observability, and deployment expectations stated where the feature is customer-facing — **Aligned**: FR-013–FR-018, User Story 4, and edge cases address security and observability.
- Ambiguous Webex details (schema, media format, auth) use `NEEDS CLARIFICATION`—not silent assumptions — **Aligned**: No unresolved clarification markers; schema defaults and SDK-delegated auth documented in Assumptions.
