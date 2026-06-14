"""Integration tests for webhook handling with mocked SDK."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from webex_byova.models.auth import ServiceAppTokens

from src.webhooks import routes


@pytest.mark.asyncio
async def test_webhook_authorized_ack(client, monkeypatch):
    sa_tokens = ServiceAppTokens(access_token="access-token-value", expires_in=3600)

    class AuthorizedResult:
        org_id = "org-123"
        event = "authorized"
        tokens = sa_tokens

    fake_sdk = MagicMock()
    fake_sdk.ahandle_service_app_webhook = AsyncMock(return_value=AuthorizedResult())
    routes.set_sdk(fake_sdk)

    monkeypatch.setattr(
        "src.webhooks.routes.register_datasource_for_org",
        AsyncMock(),
    )

    response = await client.post("/webhooks/webex", json={"resource": "serviceApp", "event": "authorized"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["org_id"] == "org-123"
    assert body["event"] == "authorized"


@pytest.mark.asyncio
async def test_webhook_deauthorized_ack(client):
    class DeauthorizedResult:
        org_id = "org-456"
        event = "deauthorized"

    fake_sdk = MagicMock()
    fake_sdk.ahandle_service_app_webhook = AsyncMock(return_value=DeauthorizedResult())
    routes.set_sdk(fake_sdk)

    response = await client.post(
        "/webhooks/webex",
        json={"resource": "serviceApp", "event": "deauthorized"},
    )
    assert response.status_code == 200
    assert response.json()["event"] == "deauthorized"
