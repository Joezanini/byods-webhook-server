"""Construct SDK clients and persistence backends from settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from webex_byova import BYOVA
from webex_byova.auth.storage import InMemoryTokenStorage
from webex_byova.auth.credentials import load_credentials_from_env

from src.persistence.audit_repository import AuditRepository, NoOpAuditRepository, create_audit_repository
from src.persistence.catalog_repository import (
    DynamoDBCatalogRepository,
    InMemoryCatalogRepository,
    create_catalog_repository,
)
from src.persistence.client import DynamoDBTable
from src.persistence.token_storage import DynamoDBTokenStorage

if TYPE_CHECKING:
    from src.config.settings import Settings


@dataclass
class PersistenceResources:
    """Application-scoped persistence handles."""

    token_storage: Any
    catalog_repository: InMemoryCatalogRepository | DynamoDBCatalogRepository
    audit_repository: AuditRepository | NoOpAuditRepository

    async def aclose(self) -> None:
        return None


async def create_persistence_resources(settings: "Settings") -> PersistenceResources:
    """Initialize token storage, catalog, and audit repositories."""
    catalog_repository = create_catalog_repository(settings)
    audit_repository = create_audit_repository(settings)

    if settings.persistence_backend == "memory":
        storage = InMemoryTokenStorage()
        return PersistenceResources(
            token_storage=storage,
            catalog_repository=catalog_repository,
            audit_repository=audit_repository,
        )

    if not settings.persistence_encryption_key:
        raise ValueError(
            "PERSISTENCE_ENCRYPTION_KEY is required when PERSISTENCE_BACKEND=dynamodb"
        )

    table = DynamoDBTable(
        table_name=settings.dynamodb_table_name,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )
    storage = DynamoDBTokenStorage(table, encryption_key=settings.persistence_encryption_key)
    return PersistenceResources(
        token_storage=storage,
        catalog_repository=catalog_repository,
        audit_repository=audit_repository,
    )


def create_sdk(settings: "Settings", token_storage: Any) -> BYOVA:
    """Construct BYOVA with custom token storage."""
    integration, service_app = load_credentials_from_env()
    return BYOVA(integration, service_app, token_storage=token_storage)


async def create_token_storage(settings: "Settings"):
    """Return persistence resources (includes token storage)."""
    return await create_persistence_resources(settings)


__all__ = [
    "PersistenceResources",
    "create_audit_repository",
    "create_catalog_repository",
    "create_persistence_resources",
    "create_sdk",
    "create_token_storage",
]
