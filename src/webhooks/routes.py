"""Webex serviceApp webhook HTTP routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from webex_byova import BYOVA
from webex_byova.exceptions import AuthenticationError, ValidationError

from src.common.logging import log_event
from src.webhooks.datasource_register import register_datasource_for_org

logger = logging.getLogger("byods-webhook-server.webhooks")
router = APIRouter()

_sdk: BYOVA | None = None


def set_sdk(sdk: BYOVA) -> None:
    """Inject the shared BYOVA SDK instance (called from app lifespan)."""
    global _sdk
    _sdk = sdk


def get_sdk() -> BYOVA:
    if _sdk is None:
        raise RuntimeError("BYOVA SDK not initialized")
    return _sdk


@router.post("/webhooks/webex")
async def webex_webhook(request: Request) -> dict[str, Any]:
    """Receive and process serviceApp authorized/deauthorized webhooks."""
    sdk = get_sdk()
    request_id = getattr(request.state, "request_id", None)
    payload = await request.json()

    try:
        result = await sdk.ahandle_service_app_webhook(payload)
    except ValidationError as exc:
        log_event(
            logger,
            logging.WARNING,
            f"Rejected webhook payload: {exc}",
            operation="webhook",
            outcome="rejected",
            request_id=request_id,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AuthenticationError as exc:
        log_event(
            logger,
            logging.ERROR,
            f"Authentication error handling webhook: {exc}",
            operation="webhook",
            outcome="failure",
            request_id=request_id,
        )
        raise HTTPException(
            status_code=503,
            detail="Integration not authorized; check WEBEX_INTEGRATION_REFRESH_TOKEN",
        ) from exc

    log_event(
        logger,
        logging.INFO,
        f"serviceApp {result.event}",
        org_id=result.org_id,
        operation="webhook",
        outcome="success",
        request_id=request_id,
    )

    if result.event == "authorized":
        logger.info(
            "serviceApp authorized: org_id=%s access_token=%s... expires_in=%s",
            result.org_id,
            result.tokens.access_token[:12],
            result.tokens.expires_in,
        )
        await register_datasource_for_org(sdk, result.org_id)
    elif result.event == "deauthorized":
        logger.info("serviceApp deauthorized: org_id=%s", result.org_id)

    return {"status": "ok", "org_id": result.org_id, "event": result.event}
