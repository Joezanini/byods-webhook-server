"""Unit tests for DynamoDB token storage."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from webex_byova.auth.storage import ServiceAppTokens

from src.persistence.token_storage import DynamoDBTokenStorage


@pytest.fixture
def encryption_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def table() -> MagicMock:
    mock = MagicMock()
    mock.get_item = AsyncMock(return_value={})
    mock.put_item = AsyncMock()
    mock.delete_item = AsyncMock()
    mock.scan = AsyncMock(return_value={"Items": []})
    return mock


@pytest.mark.asyncio
async def test_set_and_get_service_app_tokens(table, encryption_key):
    storage = DynamoDBTokenStorage(table, encryption_key=encryption_key)
    tokens = ServiceAppTokens(
        access_token="org-access",
        expires_in=3600,
        obtained_at=datetime.now(UTC),
    )

    captured: dict = {}

    async def put_item(**kwargs):
        captured.update(kwargs["Item"])

    table.put_item = AsyncMock(side_effect=put_item)

    async def get_item(**kwargs):
        if kwargs["Key"]["SK"] == "CREDS":
            return {"Item": captured}
        return {}

    table.get_item = AsyncMock(side_effect=get_item)

    await storage.set_service_app_tokens("org-1", tokens)
    restored = await storage.get_service_app_tokens("org-1")
    assert restored is not None
    assert restored.access_token == "org-access"


@pytest.mark.asyncio
async def test_integration_tokens_missing_returns_none(table, encryption_key):
    storage = DynamoDBTokenStorage(table, encryption_key=encryption_key)
    assert await storage.get_integration_tokens() is None


@pytest.mark.asyncio
async def test_set_and_get_integration_tokens(table, encryption_key):
    from webex_byova.auth.storage import OAuthTokens

    storage = DynamoDBTokenStorage(table, encryption_key=encryption_key)
    tokens = OAuthTokens(
        access_token="integration-access",
        refresh_token="integration-refresh",
        expires_in=3600,
        obtained_at=datetime.now(UTC),
    )

    captured: dict = {}

    async def put_item(**kwargs):
        captured.update(kwargs["Item"])

    table.put_item = AsyncMock(side_effect=put_item)

    async def get_item(**kwargs):
        key = kwargs["Key"]
        if key.get("PK") == "INTEGRATION" and key.get("SK") == "CREDS":
            return {"Item": captured}
        return {}

    table.get_item = AsyncMock(side_effect=get_item)

    await storage.set_integration_tokens(tokens)
    restored = await storage.get_integration_tokens()
    assert restored is not None
    assert restored.access_token == "integration-access"
    assert restored.refresh_token == "integration-refresh"


@pytest.mark.asyncio
async def test_integration_tokens_overwrite_on_reauth(table, encryption_key):
    from webex_byova.auth.storage import OAuthTokens

    storage = DynamoDBTokenStorage(table, encryption_key=encryption_key)
    store: dict = {}

    async def put_item(**kwargs):
        store.clear()
        store.update(kwargs["Item"])

    table.put_item = AsyncMock(side_effect=put_item)
    table.get_item = AsyncMock(side_effect=lambda **kwargs: {"Item": dict(store)} if store else {})

    await storage.set_integration_tokens(
        OAuthTokens(access_token="first", expires_in=3600, obtained_at=datetime.now(UTC))
    )
    await storage.set_integration_tokens(
        OAuthTokens(access_token="second", expires_in=3600, obtained_at=datetime.now(UTC))
    )
    restored = await storage.get_integration_tokens()
    assert restored is not None
    assert restored.access_token == "second"


@pytest.mark.asyncio
async def test_delete_service_app_tokens(table, encryption_key):
    storage = DynamoDBTokenStorage(table, encryption_key=encryption_key)
    await storage.delete_service_app_tokens("org-1")
    table.delete_item.assert_awaited()
    assert table.put_item.await_count >= 1
