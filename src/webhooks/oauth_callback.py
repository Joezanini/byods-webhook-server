"""Webex Integration OAuth callback HTTP handler."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from webex_byova import BYOVA
from webex_byova.exceptions import AuthenticationError

from src.common.logging import log_event
from src.config.settings import Settings, get_settings
from src.webhooks.integration_bootstrap import ensure_service_app_webhooks_if_configured
from src.webhooks.routes import get_sdk

logger = logging.getLogger("byods-webhook-server.oauth")

_sdk: BYOVA | None = None
_token_storage: Any | None = None
_settings: Settings | None = None

router = APIRouter()


def set_oauth_dependencies(
    sdk: BYOVA,
    token_storage: Any,
    settings: Settings | None = None,
) -> None:
    """Inject SDK, token storage, and settings (called from app lifespan)."""
    global _sdk, _token_storage, _settings
    _sdk = sdk
    _token_storage = token_storage
    _settings = settings


def _get_token_storage() -> Any:
    if _token_storage is None:
        raise RuntimeError("Token storage not initialized for OAuth callback")
    return _token_storage


def _get_settings() -> Settings:
    return _settings or get_settings()


def _html_success() -> HTMLResponse:
    return HTMLResponse(
        content=(
            "<!DOCTYPE html><html><head><title>Authorization successful</title></head>"
            "<body><h1>Integration authorized successfully</h1>"
            "<p>You may close this window. Service app webhooks will be verified shortly.</p>"
            "</body></html>"
        ),
        status_code=200,
    )


def _html_failure(message: str, *, status_code: int = 400) -> HTMLResponse:
    safe_message = message.replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        content=(
            f"<!DOCTYPE html><html><head><title>Authorization failed</title></head>"
            f"<body><h1>Integration authorization failed</h1>"
            f"<p>{safe_message}</p>"
            f"<p>Check server logs for request correlation ID, then retry OAuth.</p>"
            "</body></html>"
        ),
        status_code=status_code,
    )


async def handle_oauth_callback(request: Request) -> HTMLResponse:
    """Process Webex OAuth redirect: exchange code, persist tokens, ensure webhooks."""
    request_id = getattr(request.state, "request_id", None)

    error = request.query_params.get("error")
    if error:
        description = request.query_params.get("error_description") or error
        log_event(
            logger,
            logging.WARNING,
            "OAuth callback returned error from Webex",
            operation="oauth_callback",
            outcome="failure",
            request_id=request_id,
        )
        return _html_failure(f"Webex reported: {description}")

    code = request.query_params.get("code")
    if not code:
        log_event(
            logger,
            logging.WARNING,
            "OAuth callback missing authorization code",
            operation="oauth_callback",
            outcome="failure",
            request_id=request_id,
        )
        return _html_failure("Missing authorization code. Restart OAuth from the developer portal.")

    sdk = _sdk or get_sdk()
    token_storage = _get_token_storage()
    settings = _get_settings()

    # Best-effort: externally initiated flows may omit state (v1 limitation).
    state = request.query_params.get("state")
    if state is not None and state.strip() == "":
        log_event(
            logger,
            logging.WARNING,
            "OAuth callback received empty state parameter",
            operation="oauth_callback",
            outcome="failure",
            request_id=request_id,
        )
        return _html_failure("Invalid OAuth state parameter.")

    try:
        tokens = await sdk.integration.aexchange_code(code)
    except AuthenticationError as exc:
        log_event(
            logger,
            logging.WARNING,
            f"Authorization code exchange failed: {exc}",
            operation="oauth_callback",
            outcome="failure",
            request_id=request_id,
        )
        return _html_failure(
            "Could not exchange authorization code. It may be expired or already used."
        )

    try:
        await token_storage.set_integration_tokens(tokens)
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            f"Failed to persist integration tokens after exchange: {exc}",
            operation="oauth_callback",
            outcome="failure",
            request_id=request_id,
        )
        return _html_failure(
            "Tokens were issued by Webex but could not be saved. Retry OAuth once storage is available.",
            status_code=502,
        )

    try:
        await ensure_service_app_webhooks_if_configured(sdk, settings)
    except AuthenticationError:
        log_event(
            logger,
            logging.ERROR,
            "Integration tokens saved but webhook ensure failed",
            operation="oauth_callback",
            outcome="partial_failure",
            request_id=request_id,
        )
        return _html_failure(
            "Integration authorized and tokens saved, but webhook registration failed. "
            "Restart the server or run scripts/register_webhooks.py.",
            status_code=502,
        )

    log_event(
        logger,
        logging.INFO,
        "Integration OAuth callback completed successfully",
        operation="oauth_callback",
        outcome="success",
        request_id=request_id,
    )
    return _html_success()


def register_oauth_callback_route(main_router: APIRouter, settings: Settings) -> None:
    """Register GET handler at the configured integration redirect path."""
    path = settings.integration_redirect_path

    @main_router.get(path, response_class=HTMLResponse, tags=["oauth"])
    async def oauth_callback(request: Request) -> HTMLResponse:
        return await handle_oauth_callback(request)
