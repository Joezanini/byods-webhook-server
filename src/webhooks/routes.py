"""Webex serviceApp webhook HTTP routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from webex_byova import BYOVA
from webex_byova.exceptions import AuthenticationError, ValidationError

from src.common.logging import log_event
from src.persistence.audit_repository import AuditEventType, AuditOutcome
from src.webhooks.datasource_register import register_datasource_for_org

logger = logging.getLogger("byods-webhook-server.webhooks")
router = APIRouter()

_sdk: BYOVA | None = None
_audit_repository: Any | None = None


def set_sdk(sdk: BYOVA) -> None:
    """Inject the shared BYOVA SDK instance (called from app lifespan)."""
    global _sdk
    _sdk = sdk


def set_audit_repository(repository: Any) -> None:
    """Inject audit repository (optional P3)."""
    global _audit_repository
    _audit_repository = repository


def get_sdk() -> BYOVA:
    if _sdk is None:
        raise RuntimeError("BYOVA SDK not initialized")
    return _sdk


async def _record_audit(
    *,
    org_id: str,
    event_type: AuditEventType,
    outcome: AuditOutcome,
    request_id: str | None,
    detail: str | None = None,
) -> None:
    if _audit_repository is None:
        return
    try:
        await _audit_repository.record_event(
            org_id=org_id,
            event_type=event_type,
            outcome=outcome,
            request_id=request_id,
            detail=detail,
        )
    except Exception:
        logger.exception("Failed to write audit event for org_id=%s", org_id)


@router.post("/webhooks/webex")
async def webex_webhook(request: Request) -> dict[str, Any]:
    """Receive and process serviceApp authorized/deauthorized webhooks."""
    sdk = get_sdk()
    request_id = getattr(request.state, "request_id", None)
    payload = await request.json()
    org_id = str(payload.get("orgId") or payload.get("org_id") or "unknown")

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
        await _record_audit(
            org_id=org_id,
            event_type=AuditEventType.PROCESSING_FAILURE,
            outcome=AuditOutcome.FAILURE,
            request_id=request_id,
            detail=str(exc),
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
        await _record_audit(
            org_id=org_id,
            event_type=AuditEventType.PROCESSING_FAILURE,
            outcome=AuditOutcome.FAILURE,
            request_id=request_id,
            detail=str(exc),
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
        logger.info("serviceApp authorized: org_id=%s", result.org_id)
        await register_datasource_for_org(sdk, result.org_id)
        await _record_audit(
            org_id=result.org_id,
            event_type=AuditEventType.AUTHORIZED,
            outcome=AuditOutcome.SUCCESS,
            request_id=request_id,
        )
    elif result.event == "deauthorized":
        logger.info("serviceApp deauthorized: org_id=%s", result.org_id)
        await _record_audit(
            org_id=result.org_id,
            event_type=AuditEventType.DEAUTHORIZED,
            outcome=AuditOutcome.SUCCESS,
            request_id=request_id,
        )

    return {"status": "ok", "org_id": result.org_id, "event": result.event}
