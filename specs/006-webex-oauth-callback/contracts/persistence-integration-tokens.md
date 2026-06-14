# Contract: Integration Token Persistence Extension

**Feature**: `006-webex-oauth-callback` | **Extends**: [005 persistence-storage.md](../../005-persistent-app-state/contracts/persistence-storage.md)

Documents changes to `DynamoDBTokenStorage` for integration OAuth tokens.

---

## `DynamoDBTokenStorage` — integration token methods

**Supersedes** 005 contract row: `set/get_integration_tokens` now perform DynamoDB I/O when `PERSISTENCE_BACKEND=dynamodb`.

| Method | DynamoDB effect |
|--------|-----------------|
| `get_integration_tokens` | Get `PK=INTEGRATION`, `SK=CREDS`; decrypt `token_blob` → `OAuthTokens` |
| `set_integration_tokens` | Put `INTEGRATION/CREDS` (encrypted); atomic replace |
| `get/set_service_app_tokens` | Unchanged (org-scoped) |

**Memory backend** (`PERSISTENCE_BACKEND=memory`): Full `InMemoryTokenStorage` behavior for both integration and org tokens (tests).

---

## DynamoDB item — Integration credentials

**Keys**: `PK=INTEGRATION`, `SK=CREDS`

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
  "expires_in": 1209599,
  "obtained_at": "2026-06-13T12:00:00Z",
  "token_type": "Bearer",
  "refresh_token_expires_in": 7775999
}
```

Reuse `src/persistence/encryption.py` helpers; add `_oauth_tokens_to_payload` / `_payload_to_oauth_tokens` mirroring service app token serializers in `token_storage.py`.

---

## Error handling

| Condition | Behavior |
|-----------|----------|
| `set_integration_tokens` DynamoDB error during callback | Propagate; callback returns failure HTML; no in-memory token update |
| `get_integration_tokens` miss | Return `None`; startup falls back to env refresh token |
| Decrypt failure | Log error; treat as missing tokens; do not crash webhook handler |

---

## SDK refresh persistence

`IntegrationTokenManager.arefresh` calls `set_integration_tokens` after successful refresh. DynamoDB implementation MUST persist refreshed access token (and refresh token if rotated) on every refresh cycle (FR-008, SC-006).

---

## Testing contract

Unit tests (`tests/unit/test_token_storage.py`):
- Round-trip integration tokens through encrypt/decrypt
- `get_integration_tokens` returns `None` when item missing
- `set_integration_tokens` overwrites prior item (re-authorization)

Integration test (`tests/integration/test_oauth_callback.py`):
- Mock `aexchange_code`; verify DynamoDB item written
- Simulate persistence failure → callback error response, no item written
