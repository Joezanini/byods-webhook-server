"""Factory for the SDK BYOVA media server."""

from __future__ import annotations

from typing import TYPE_CHECKING

from webex_byova.media import BYOVAMediaServer
from webex_byova.media.config import MediaServerConfig

from src.byova.catalog import VirtualAgentCatalogEntry
from src.byova.sdk_patch import apply_sdk_catalog_patch, sdk_supports_native_catalog
from src.config.settings import Settings

if TYPE_CHECKING:
    from src.persistence.catalog_repository import (
        DynamoDBCatalogRepository,
        InMemoryCatalogRepository,
    )


async def create_media_server(
    settings: Settings,
    catalog_repository: "InMemoryCatalogRepository | DynamoDBCatalogRepository",
) -> BYOVAMediaServer:
    """Create a BYOVAMediaServer with virtual agent catalog from persistence."""
    apply_sdk_catalog_patch()

    catalog: list[VirtualAgentCatalogEntry] = await catalog_repository.list_agents()
    config = MediaServerConfig.from_env()

    if sdk_supports_native_catalog():
        from webex_byova.media.config import VirtualAgentConfig

        virtual_agents = [
            VirtualAgentConfig(
                virtual_agent_id=entry.virtual_agent_id,
                virtual_agent_name=entry.virtual_agent_name,
                is_default=entry.is_default,
            )
            for entry in catalog
        ]
        config = config.model_copy(update={"virtual_agents": virtual_agents})

    server = BYOVAMediaServer(config)
    server._virtual_agent_catalog = catalog  # noqa: SLF001
    server._catalog_repository = catalog_repository  # noqa: SLF001

    async def refresh_catalog() -> list[VirtualAgentCatalogEntry]:
        entries = await catalog_repository.list_agents()
        server._virtual_agent_catalog = entries  # noqa: SLF001
        return entries

    server._catalog_refresh = refresh_catalog  # noqa: SLF001
    return server
