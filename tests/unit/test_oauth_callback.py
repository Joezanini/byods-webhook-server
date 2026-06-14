"""Unit tests for Integration OAuth callback handler."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from webex_byova.auth.storage import OAuthTokens
from webex_byova.exceptions import AuthenticationError

from src.webhooks import oauth_callback


def _make_request(query: str = "") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/oauth/webex/callback",
        "query_string": query.encode(),
        "headers": [],
    }
    request = Request(scope)
    request.state.request_id = "req-test"
    return request


@pytest.fixture(autouse=True)
def reset_oauth_deps():
    oauth_callback._sdk = None
    oauth_callback._token_storage = None
    oauth_callback._settings = None
    yield


@pytest.mark.asyncio
async def test_callback_missing_code_returns_failure_html():
    response = await oauth_callback.handle_oauth_callback(_make_request())
    assert response.status_code == 400
    assert b"Missing authorization code" in response.body


@pytest.mark.asyncio
async def test_callback_oauth_error_returns_failure_html():
    response = await oauth_callback.handle_oauth_callback(
        _make_request("error=access_denied&error_description=User%20denied")
    )
    assert response.status_code == 400
    assert b"User denied" in response.body


@pytest.mark.asyncio
async def test_callback_success_persists_and_ensures_webhooks():
    sdk = MagicMock()
    sdk.integration.aexchange_code = AsyncMock(
        return_value=OAuthTokens(
            access_token="access",
            refresh_token="refresh",
            expires_in=3600,
            obtained_at=datetime.now(UTC),
        )
    )
    sdk.webhooks.aensure_service_app_webhooks = AsyncMock(return_value=[])

    token_storage = MagicMock()
    token_storage.set_integration_tokens = AsyncMock()

    oauth_callback.set_oauth_dependencies(sdk, token_storage)

    settings = MagicMock()
    settings.webhook_target_url = "https://example.com/webhooks/webex"
    oauth_callback._settings = settings

    with patch(
        "src.webhooks.oauth_callback.ensure_service_app_webhooks_if_configured",
        new=AsyncMock(),
    ) as ensure:
        response = await oauth_callback.handle_oauth_callback(_make_request("code=abc123"))

    assert response.status_code == 200
    assert b"authorized successfully" in response.body
    sdk.integration.aexchange_code.assert_awaited_once_with("abc123")
    token_storage.set_integration_tokens.assert_awaited_once()
    ensure.assert_awaited_once()


@pytest.mark.asyncio
async def test_callback_persistence_failure_discards_tokens():
    sdk = MagicMock()
    sdk.integration.aexchange_code = AsyncMock(
        return_value=OAuthTokens(
            access_token="access",
            expires_in=3600,
            obtained_at=datetime.now(UTC),
        )
    )

    token_storage = MagicMock()
    token_storage.set_integration_tokens = AsyncMock(side_effect=RuntimeError("dynamodb down"))

    oauth_callback.set_oauth_dependencies(sdk, token_storage)

    response = await oauth_callback.handle_oauth_callback(_make_request("code=abc123"))

    assert response.status_code == 502
    assert b"could not be saved" in response.body


@pytest.mark.asyncio
async def test_callback_exchange_failure_returns_failure_html():
    sdk = MagicMock()
    sdk.integration.aexchange_code = AsyncMock(
        side_effect=AuthenticationError("invalid code")
    )
    token_storage = MagicMock()
    oauth_callback.set_oauth_dependencies(sdk, token_storage)

    response = await oauth_callback.handle_oauth_callback(_make_request("code=bad"))

    assert response.status_code == 400
    token_storage.set_integration_tokens.assert_not_called()
