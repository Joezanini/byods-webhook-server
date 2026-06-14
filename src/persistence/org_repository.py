"""Org authorization profile persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from src.persistence.client import DynamoDBTable


class AuthorizationState(StrEnum):
    AUTHORIZED = "authorized"
    DEAUTHORIZED = "deauthorized"


def _org_pk(org_id: str) -> str:
    return f"ORG#{org_id}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def upsert_authorized(table: DynamoDBTable, org_id: str) -> None:
    """Mark org as authorized and refresh timestamps."""
    now = _now_iso()
    await table.put_item(
        Item={
            "PK": _org_pk(org_id),
            "SK": "PROFILE",
            "authorization_state": AuthorizationState.AUTHORIZED,
            "authorized_at": now,
            "deauthorized_at": None,
            "updated_at": now,
        }
    )


async def mark_deauthorized(table: DynamoDBTable, org_id: str) -> None:
    """Mark org as deauthorized."""
    now = _now_iso()
    await table.put_item(
        Item={
            "PK": _org_pk(org_id),
            "SK": "PROFILE",
            "authorization_state": AuthorizationState.DEAUTHORIZED,
            "deauthorized_at": now,
            "updated_at": now,
        }
    )


async def get_profile(table: DynamoDBTable, org_id: str) -> dict | None:
    """Return org profile item or None."""
    response = await table.get_item(Key={"PK": _org_pk(org_id), "SK": "PROFILE"})
    return response.get("Item")
