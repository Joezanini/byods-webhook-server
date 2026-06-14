# Contract: Virtual Agent Catalog Management (CLI)

**Feature**: `005-persistent-app-state` | Replaces file-only catalog from feature 002

Operators manage the durable catalog via CLI. Flow Designer discovery reads from DynamoDB (read-through), not from the JSON file at runtime.

---

## Script: `scripts/manage_virtual_agents.py`

Mirrors `scripts/manage_datasources.py` conventions (argparse, async SDK bootstrap where needed, structured stderr on validation errors).

### Commands

| Command | Args | Effect |
|---------|------|--------|
| `list` | — | Print all catalog entries (id, name, default flag) |
| `add` | `--id`, `--name`, `[--default]` | Add agent; reject duplicates |
| `update` | `--id`, `[--name]`, `[--default]` | Update fields; validate aggregate rules |
| `remove` | `--id` | Delete agent; reject if last agent |
| `set-default` | `--id` | Clear other defaults; set one default |

### Validation errors (exit code 1, stderr)

| Code | Message theme |
|------|---------------|
| `DUPLICATE_ID` | Agent id already exists |
| `NOT_FOUND` | Agent id not found |
| `EMPTY_CATALOG` | Cannot remove last agent |
| `MULTIPLE_DEFAULTS` | More than one default after mutation |
| `INVALID_NAME` | Empty display name |

### Environment

Uses same persistence env vars as server (`DYNAMODB_TABLE_NAME`, `PERSISTENCE_ENCRYPTION_KEY`, `AWS_*`). Does **not** require Webex credentials for catalog-only operations.

---

## Discovery integration

**File**: `src/byova/server.py` / `src/byova/handlers.py`

On `list_virtual_agents` event (before response):

1. `entries = await catalog_repository.list_agents()`
2. Validate aggregate (defensive; should always pass if CLI validated)
3. Update in-process SDK catalog if native catalog API supports runtime refresh; otherwise rebuild `MediaServerConfig.virtual_agents` on server (document limitation if SDK requires restart—prefer read-through mapping in handler patch)

**Startup** (`create_media_server`):

1. `await catalog_repository.ensure_seeded(settings.virtual_agents_config_path)`
2. Load entries into `MediaServerConfig.virtual_agents`

---

## JSON seed file (bootstrap only)

**Path**: `WEBEX_VIRTUAL_AGENTS_CONFIG` (default `config/virtual_agents.json`)

Used once when `CATALOG/META` absent: import entries into DynamoDB, set `seeded_from_file=true`. After seed, file edits have no effect until operator re-runs a future `import` subcommand (optional v1: seed-on-empty only).

---

## Feature 002 compatibility

| Feature 002 behavior | Feature 005 change |
|---------------------|-------------------|
| Startup fail on invalid JSON file | Fail if DynamoDB catalog invalid OR seed file invalid on first bootstrap |
| `load_catalog(path)` | `CatalogRepository.list_agents()` |
| Operator edits JSON + restart | Operator runs CLI; discovery updates without restart (read-through) |
| Validation rules (unique id, one default, ≥1 agent) | Unchanged semantics |
