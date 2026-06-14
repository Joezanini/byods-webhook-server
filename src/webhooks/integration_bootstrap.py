"""Integration OAuth bootstrap and webhook ensure helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from webex_byova import BYOVA
from webex_byova.exceptions import AuthenticationError

if TYPE_CHECKING:
    from src.config.settings import Settings

logger = logging.getLogger("byods-webhook-server.integration")


async def bootstrap_integration(
    sdk: BYOVA,
    settings: "Settings",
    token_storage: Any,
) -> bool:
    """Load integration tokens storage-first, refresh, and mark ready for Webex API calls."""
    try:
        stored = await token_storage.get_integration_tokens()
        if stored:
            tokens = await sdk.integration.arefresh()
            logger.info(
                "Integration tokens loaded from durable storage (expires at %s)",
                tokens.expires_at,
            )
            return True

        refresh_token = settings.integration_refresh_token
        if refresh_token:
            tokens = await sdk.integration.arefresh(refresh_token)
            logger.info(
                "Integration tokens bootstrapped from env (expires at %s)",
                tokens.expires_at,
            )
            return True

        logger.warning(
            "No integration tokens in durable storage and WEBEX_INTEGRATION_REFRESH_TOKEN "
            "is not set; complete OAuth via the production callback URL"
        )
        return False
    except AuthenticationError as exc:
        logger.error("Failed to bootstrap Integration tokens: %s", exc)
        return False


async def ensure_service_app_webhooks_if_configured(
    sdk: BYOVA,
    settings: "Settings",
) -> None:
    """List-then-create service app webhooks when target URL is configured."""
    target = (settings.webhook_target_url or "").strip()
    if not target:
        return
    try:
        created = await sdk.webhooks.aensure_service_app_webhooks(target)
        if created:
            logger.info(
                "Registered %d serviceApp webhook(s) for target %s",
                len(created),
                target,
            )
        else:
            logger.info(
                "Service app webhooks already registered for target %s",
                target,
            )
    except AuthenticationError as exc:
        logger.error("Failed to ensure service app webhooks: %s", exc)
        raise
