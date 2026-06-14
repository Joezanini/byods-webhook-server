# Contract: DynamoDB Persistence & SDK Token Storage

**Feature**: `005-persistent-app-state` | **SDK**: `webex-byova` `TokenStorage` protocol

Documents the persistence layer boundary between the application, SDK, and DynamoDB. Implementation in `src/persistence/`.

---

## Module layout

| Module | Responsibility |
|--------|----------------|
| `src/persistence/token_storage.py` | `DynamoDBTokenStorage` implements SDK `TokenStorage` |
| `src/persistence/org_repository.py` | Org profile CRUD (`PROFILE` items) |
| `src/persistence/catalog_repository.py` | Catalog load/save/validate (`CATALOG/*` items) |
| `src/persistence/audit_repository.py` | Append-only audit writes + CLI query helper |
| `src/persistence/encryption.py` | Fernet encrypt/decrypt for token blobs |
| `src/persistence/client.py` | Shared boto3/aioboto3 table handle |
| `src/persistence/factory.py` | `create_token_storage(settings)` — selects backend |

---

## SDK: `TokenStorage` implementation

**Class**: `DynamoDBTokenStorage`

```python
class DynamoDBTokenStorage:
    """Async TokenStorage backed by DynamoDB (service app tokens only)."""

    async def get_integration_tokens(self) -> OAuthTokens | None: ...
    async def set_integration_tokens(self, tokens: OAuthTokens) -> None: ...
    async def get_service_app_tokens(self, org_id: str) -> ServiceAppTokens | None: ...
    async def set_service_app_tokens(self, org_id: str, tokens: ServiceAppTokens) -> None: ...
    async def delete_service_app_tokens(self, org_id: str) -> None: ...
    async def list_registered_orgs(self) -> list[str]: ...
```

**Behavior**:

| Operation | DynamoDB effect | Profile effect |
|-----------|-----------------|----------------|
| `set_service_app_tokens` | Put `CREDS` (encrypted) | Upsert `PROFILE`: `authorized`, `authorized_at` |
| `delete_service_app_tokens` | Delete `CREDS` | Update `PROFILE`: `deauthorized`, `deauthorized_at` |
| `get_service_app_tokens` | Get `CREDS` by org | — |
| `list_registered_orgs` | Query `PK` prefix `ORG#` where `SK=CREDS` exists | — |
| `set/get_integration_tokens` | **No DynamoDB I/O** | In-memory delegate |

**SDK wiring** (`main.py` lifespan):

```python
storage = create_token_storage(settings)
sdk = BYOVA(integration=..., service_app=..., token_storage=storage)
```

Replace `BYOVA.from_env()` when custom storage is required (load credentials from env, pass explicit `BYOVA(...)`).

---

## DynamoDB item schemas

### Org profile — `PK=ORG#{org_id}`, `SK=PROFILE`

```json
{
  "authorization_state": "authorized",
  "authorized_at": "2026-06-13T12:00:00Z",
  "deauthorized_at": null,
  "updated_at": "2026-06-13T12:00:00Z"
}
```

### Org credentials — `PK=ORG#{org_id}`, `SK=CREDS`

```json
{
  "token_blob": "<fernet-ciphertext>",
  "ciphertext_version": 1,
  "updated_at": "2026-06-13T12:00:00Z"
}
```

Plaintext before encryption (never stored):

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_in": 3600,
  "obtained_at": "2026-06-13T12:00:00Z",
  "token_type": "Bearer"
}
```

### Catalog agent — `PK=CATALOG`, `SK=AGENT#{virtual_agent_id}`

```json
{
  "virtual_agent_id": "1",
  "virtual_agent_name": "Travel Booking Agent",
  "is_default": false
}
```

### Catalog meta — `PK=CATALOG`, `SK=META`

```json
{
  "entry_count": 6,
  "updated_at": "2026-06-13T12:00:00Z",
  "seeded_from_file": true
}
```

---

## Readiness contract

`GET /ready` returns 503 when:

| Check | Condition |
|-------|-----------|
| Integration bootstrap | `integration_ready` false (unchanged) |
| DynamoDB | `PERSISTENCE_BACKEND=dynamodb` and table unreachable or `CATALOG/META` missing with empty table and seed failed |

Returns 200 when integration ready and persistence backend healthy.

---

## Unchanged HTTP contracts

- `POST /webhooks/webex` — same request/response shape; persistence is internal
- `GET /health` — unchanged liveness
- gRPC `ListVirtualAgents` — same response schema; catalog source changes internally

---

## CDK outputs (new)

| Output | Description |
|--------|-------------|
| `AppStateTableName` | DynamoDB table name for ECS env |
| `AppStateTableArn` | For IAM documentation |

ECS task environment additions:

```
DYNAMODB_TABLE_NAME=<table name>
PERSISTENCE_BACKEND=dynamodb
```

Secrets Manager addition on `byods-webhook-server/webex`:

```
PERSISTENCE_ENCRYPTION_KEY=<fernet key>
```
