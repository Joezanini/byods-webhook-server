"""Start and stop the SDK media server."""

from __future__ import annotations

import logging

from webex_byova.media import BYOVAMediaServer

from src.byova.handlers import register_handlers
from src.config.settings import Settings

logger = logging.getLogger("byods-webhook-server.media")


async def start_media_server(server: BYOVAMediaServer, settings: Settings) -> None:
    """Register handlers and start the gRPC media server."""
    catalog = getattr(server, "_virtual_agent_catalog", [])
    config_path = getattr(server, "_virtual_agents_config_path", settings.virtual_agents_config_path)
    logger.info(
        "Virtual agent catalog loaded: %s agents from %s",
        len(catalog),
        config_path,
    )

    register_handlers(server, settings)
    await server.start()
    logger.info(
        "BYOVA media server listening on %s:%s",
        server.config.host,
        server.config.port,
    )


async def stop_media_server(server: BYOVAMediaServer) -> None:
    """Gracefully stop the gRPC media server."""
    await server.stop()
