"""Factory for the SDK BYOVA media server."""

from __future__ import annotations

from webex_byova.media import BYOVAMediaServer
from webex_byova.media.config import MediaServerConfig

from src.byova.catalog import VirtualAgentCatalogEntry, load_catalog
from src.byova.sdk_patch import apply_sdk_catalog_patch, sdk_supports_native_catalog
from src.config.settings import Settings


def create_media_server(settings: Settings) -> BYOVAMediaServer:
    """Create a BYOVAMediaServer with virtual agent catalog from configuration."""
    apply_sdk_catalog_patch()

    catalog: list[VirtualAgentCatalogEntry] = load_catalog(settings.virtual_agents_config_path)
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
    server._virtual_agents_config_path = settings.virtual_agents_config_path  # noqa: SLF001
    return server
