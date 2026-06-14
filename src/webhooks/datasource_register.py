"""Auto-register BYODS data sources after serviceApp authorization."""

from __future__ import annotations

import logging

from webex_byova import BYOVA

from src.byods.service import DuplicateDataSourceURLError, auto_register_for_org
from src.common.logging import log_event
from src.config.settings import Settings, get_settings

logger = logging.getLogger("byods-webhook-server.webhooks")


async def register_datasource_for_org(
    sdk: BYOVA,
    org_id: str,
    *,
    settings: Settings | None = None,
) -> None:
    """Register a BYODS data source for an org after serviceApp authorization."""
    cfg = settings or get_settings()
    if not cfg.auto_register_datasource:
        return

    if not cfg.build_datasource_url():
        log_event(
            logger,
            logging.WARNING,
            "Skipping data source registration: webhook target URL missing or invalid",
            org_id=org_id,
            operation="datasource_auto_register",
            outcome="skipped",
        )
        return

    try:
        created = await auto_register_for_org(sdk, org_id, cfg)
        if created is None:
            log_event(
                logger,
                logging.INFO,
                "Data source already registered",
                org_id=org_id,
                operation="datasource_auto_register",
                outcome="duplicate",
            )
            return

        log_event(
            logger,
            logging.INFO,
            f"Registered data source id={created.id} url={created.url} status={created.status}",
            org_id=org_id,
            operation="datasource_auto_register",
            outcome="success",
        )
    except DuplicateDataSourceURLError:
        log_event(
            logger,
            logging.INFO,
            "Data source already registered",
            org_id=org_id,
            operation="datasource_auto_register",
            outcome="duplicate",
        )
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            f"Failed to register data source: {exc}",
            org_id=org_id,
            operation="datasource_auto_register",
            outcome="failure",
        )
        logger.exception("Data source registration error for org_id=%s", org_id)
