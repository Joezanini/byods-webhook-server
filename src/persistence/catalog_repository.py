"""Catalog and audit persistence."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.byova.catalog import (
    CatalogLoadError,
    VirtualAgentCatalogEntry,
    load_catalog,
    validate_catalog_entries,
)
from src.persistence.client import DynamoDBTable

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger("byods-webhook-server.persistence.catalog")

CATALOG_PK = "CATALOG"


class CatalogRepositoryError(Exception):
    """Raised when catalog persistence operations fail validation."""


class InMemoryCatalogRepository:
    """File-backed catalog for PERSISTENCE_BACKEND=memory (local dev/tests)."""

    def __init__(self, config_path: str) -> None:
        self._config_path = config_path
        self._entries: list[VirtualAgentCatalogEntry] | None = None

    async def list_agents(self) -> list[VirtualAgentCatalogEntry]:
        if self._entries is None:
            self._entries = load_catalog(self._config_path)
        return list(self._entries)

    async def ensure_seeded(self, seed_path: str | Path) -> None:
        if self._entries is None:
            self._entries = load_catalog(seed_path)

    async def save_agent(self, entry: VirtualAgentCatalogEntry) -> None:
        entries = await self.list_agents()
        updated = [e for e in entries if e.virtual_agent_id != entry.virtual_agent_id]
        updated.append(entry)
        validate_catalog_entries(updated)
        self._entries = updated

    async def remove_agent(self, virtual_agent_id: str) -> None:
        entries = await self.list_agents()
        updated = [e for e in entries if e.virtual_agent_id != virtual_agent_id]
        if len(updated) == len(entries):
            raise CatalogRepositoryError(f"Agent not found: {virtual_agent_id}")
        validate_catalog_entries(updated)
        self._entries = updated

    async def replace_all(self, entries: list[VirtualAgentCatalogEntry]) -> None:
        validate_catalog_entries(entries)
        self._entries = list(entries)


class DynamoDBCatalogRepository:
    """DynamoDB-backed virtual agent catalog."""

    def __init__(
        self,
        *,
        table_name: str,
        region: str,
        endpoint_url: str | None,
    ) -> None:
        self._table_name = table_name
        self._region = region
        self._endpoint_url = endpoint_url

    def _table(self) -> DynamoDBTable:
        return DynamoDBTable(
            table_name=self._table_name,
            region=self._region,
            endpoint_url=self._endpoint_url,
        )

    async def _list_from_table(self, table: DynamoDBTable) -> list[VirtualAgentCatalogEntry]:
        response = await table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues={":pk": CATALOG_PK, ":sk": "AGENT#"},
        )
        items = response.get("Items", [])
        entries = [
            VirtualAgentCatalogEntry(
                virtual_agent_id=str(item["virtual_agent_id"]),
                virtual_agent_name=str(item["virtual_agent_name"]),
                is_default=bool(item.get("is_default", False)),
            )
            for item in items
        ]
        if not entries:
            raise CatalogLoadError("Catalog is empty in DynamoDB")
        validate_catalog_entries(entries)
        return entries

    async def list_agents(self) -> list[VirtualAgentCatalogEntry]:
        table = self._table()
        return await self._list_from_table(table)

    async def ensure_seeded(self, seed_path: str | Path) -> None:
        table = self._table()
        meta = await table.get_item(Key={"PK": CATALOG_PK, "SK": "META"})
        if meta.get("Item"):
            return
        try:
            entries = load_catalog(seed_path)
        except CatalogLoadError:
            logger.warning(
                "No seed catalog at %s; populate via scripts/manage_virtual_agents.py",
                seed_path,
            )
            return
        await self._write_entries(table, entries, seeded_from_file=True)
        logger.info("Catalog seeded from %s (%s agents)", seed_path, len(entries))

    async def _write_entries(
        self,
        table: DynamoDBTable,
        entries: list[VirtualAgentCatalogEntry],
        *,
        seeded_from_file: bool = False,
    ) -> None:
        validate_catalog_entries(entries)
        now = datetime.now(UTC).isoformat()
        existing = await table.query(
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
            ExpressionAttributeValues={":pk": CATALOG_PK, ":sk": "AGENT#"},
        )
        for item in existing.get("Items", []):
            await table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        for entry in entries:
            await table.put_item(
                Item={
                    "PK": CATALOG_PK,
                    "SK": f"AGENT#{entry.virtual_agent_id}",
                    "virtual_agent_id": entry.virtual_agent_id,
                    "virtual_agent_name": entry.virtual_agent_name,
                    "is_default": entry.is_default,
                    "updated_at": now,
                }
            )
        await table.put_item(
            Item={
                "PK": CATALOG_PK,
                "SK": "META",
                "entry_count": len(entries),
                "updated_at": now,
                "seeded_from_file": seeded_from_file,
            }
        )

    async def save_agent(self, entry: VirtualAgentCatalogEntry) -> None:
        table = self._table()
        entries = await self._list_from_table(table)
        updated = [e for e in entries if e.virtual_agent_id != entry.virtual_agent_id]
        updated.append(entry)
        await self._write_entries(table, updated)

    async def remove_agent(self, virtual_agent_id: str) -> None:
        table = self._table()
        entries = await self._list_from_table(table)
        updated = [e for e in entries if e.virtual_agent_id != virtual_agent_id]
        if len(updated) == len(entries):
            raise CatalogRepositoryError(f"Agent not found: {virtual_agent_id}")
        await self._write_entries(table, updated)

    async def replace_all(self, entries: list[VirtualAgentCatalogEntry]) -> None:
        table = self._table()
        await self._write_entries(table, entries)


def create_catalog_repository(settings: "Settings"):
    """Return catalog repository for the configured persistence backend."""
    if settings.persistence_backend == "memory":
        return InMemoryCatalogRepository(settings.virtual_agents_config_path)
    return DynamoDBCatalogRepository(
        table_name=settings.dynamodb_table_name,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )
