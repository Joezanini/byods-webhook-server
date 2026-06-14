"""SDK TokenStorage backed by DynamoDB for org-scoped service app tokens."""

from __future__ import annotations

from datetime import UTC, datetime

from webex_byova.auth.storage import InMemoryTokenStorage, OAuthTokens, ServiceAppTokens

from src.persistence import encryption as enc
from src.persistence import org_repository
from src.persistence.client import DynamoDBTable


def _org_pk(org_id: str) -> str:
    return f"ORG#{org_id}"


def _tokens_to_payload(tokens: ServiceAppTokens) -> dict:
    return {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "expires_in": tokens.expires_in,
        "token_type": tokens.token_type,
        "obtained_at": tokens.obtained_at.isoformat(),
        "refresh_token_expires_in": tokens.refresh_token_expires_in,
    }


def _payload_to_tokens(payload: dict) -> ServiceAppTokens:
    obtained_raw = payload.get("obtained_at")
    obtained_at = (
        datetime.fromisoformat(obtained_raw)
        if isinstance(obtained_raw, str)
        else datetime.now()
    )
    return ServiceAppTokens(
        access_token=str(payload["access_token"]),
        expires_in=int(payload["expires_in"]),
        token_type=str(payload.get("token_type", "Bearer")),
        refresh_token=payload.get("refresh_token"),
        refresh_token_expires_in=payload.get("refresh_token_expires_in"),
        obtained_at=obtained_at,
    )


class DynamoDBTokenStorage:
    """Persist service app tokens per org in DynamoDB; integration tokens in memory only."""

    def __init__(self, table: DynamoDBTable, *, encryption_key: str) -> None:
        self._table = table
        self._encryption_key = encryption_key
        self._integration = InMemoryTokenStorage()

    async def get_integration_tokens(self) -> OAuthTokens | None:
        return await self._integration.get_integration_tokens()

    async def set_integration_tokens(self, tokens: OAuthTokens) -> None:
        await self._integration.set_integration_tokens(tokens)

    async def get_service_app_tokens(self, org_id: str) -> ServiceAppTokens | None:
        response = await self._table.get_item(
            Key={"PK": _org_pk(org_id), "SK": "CREDS"}
        )
        item = response.get("Item")
        if not item:
            return None
        payload = enc.decrypt_token_payload(
            self._encryption_key,
            str(item["token_blob"]),
            version=int(item.get("ciphertext_version", enc.CIPHERTEXT_VERSION)),
        )
        return _payload_to_tokens(payload)

    async def set_service_app_tokens(self, org_id: str, tokens: ServiceAppTokens) -> None:
        blob, version = enc.encrypt_token_payload(
            self._encryption_key, _tokens_to_payload(tokens)
        )
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        await self._table.put_item(
            Item={
                "PK": _org_pk(org_id),
                "SK": "CREDS",
                "token_blob": blob,
                "ciphertext_version": version,
                "updated_at": now,
            }
        )
        await org_repository.upsert_authorized(self._table, org_id)

    async def delete_service_app_tokens(self, org_id: str) -> None:
        await self._table.delete_item(Key={"PK": _org_pk(org_id), "SK": "CREDS"})
        await org_repository.mark_deauthorized(self._table, org_id)

    async def list_registered_orgs(self) -> list[str]:
        # Scan for CREDS items (low volume — tens of orgs)
        org_ids: list[str] = []
        scan_kwargs: dict = {
            "FilterExpression": "SK = :sk",
            "ExpressionAttributeValues": {":sk": "CREDS"},
        }
        while True:
            response = await self._table.scan(**scan_kwargs)
            for item in response.get("Items", []):
                pk = str(item.get("PK", ""))
                if pk.startswith("ORG#"):
                    org_ids.append(pk[4:])
            if "LastEvaluatedKey" not in response:
                break
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
        return sorted(org_ids)
