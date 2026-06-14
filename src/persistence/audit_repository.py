"""Service app lifecycle audit persistence."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from src.persistence.client import DynamoDBTable

if TYPE_CHECKING:
    from src.config.settings import Settings

_TOKEN_PATTERN = re.compile(
    r"(access_token|refresh_token|Bearer\s+\S+)",
    re.IGNORECASE,
)


class AuditEventType(StrEnum):
    AUTHORIZED = "authorized"
    DEAUTHORIZED = "deauthorized"
    PROCESSING_FAILURE = "processing_failure"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


def sanitize_detail(detail: str | None, *, max_length: int = 500) -> str | None:
    """Strip token-like substrings from audit detail text."""
    if not detail:
        return None
    cleaned = _TOKEN_PATTERN.sub("[REDACTED]", detail)
    return cleaned[:max_length]


class AuditRepository:
    """Append-only audit log in DynamoDB."""

    def __init__(
        self,
        *,
        table_name: str,
        region: str,
        endpoint_url: str | None,
        ttl_days: int,
    ) -> None:
        self._table = DynamoDBTable(
            table_name=table_name,
            region=region,
            endpoint_url=endpoint_url,
        )
        self._ttl_days = ttl_days

    async def record_event(
        self,
        *,
        org_id: str,
        event_type: AuditEventType | str,
        outcome: AuditOutcome | str,
        request_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        event_id = uuid4().hex[:8]
        sk = f"AUDIT#{now.isoformat()}#{event_id}"
        expires_at = int((now + timedelta(days=self._ttl_days)).timestamp())
        await self._table.put_item(
            Item={
                "PK": f"ORG#{org_id}",
                "SK": sk,
                "org_id": org_id,
                "event_type": str(event_type),
                "outcome": str(outcome),
                "timestamp": now.isoformat(),
                "request_id": request_id,
                "detail": sanitize_detail(detail),
                "expires_at": expires_at,
            }
        )

    async def list_events(
        self,
        org_id: str,
        *,
        limit: int = 20,
        since: datetime | None = None,
    ) -> list[dict]:
        response = await self._table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues={
                ":pk": f"ORG#{org_id}",
                ":sk": "AUDIT#",
            },
            ScanIndexForward=False,
            Limit=limit,
        )
        items = response.get("Items", [])
        if since:
            since_iso = since.isoformat()
            items = [i for i in items if str(i.get("timestamp", "")) >= since_iso]
        return [
            {
                "org_id": str(item.get("org_id", org_id)),
                "event_type": str(item.get("event_type", "")),
                "outcome": str(item.get("outcome", "")),
                "timestamp": str(item.get("timestamp", "")),
                "request_id": item.get("request_id"),
                "detail": item.get("detail"),
            }
            for item in items
        ]


class NoOpAuditRepository:
    """Audit sink when persistence backend is memory."""

    async def record_event(self, **kwargs) -> None:
        return None

    async def list_events(self, org_id: str, *, limit: int = 20, since=None) -> list[dict]:
        return []


def create_audit_repository(settings: "Settings"):
    if settings.persistence_backend != "dynamodb":
        return NoOpAuditRepository()
    return AuditRepository(
        table_name=settings.dynamodb_table_name,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        ttl_days=settings.persistence_audit_ttl_days,
    )
