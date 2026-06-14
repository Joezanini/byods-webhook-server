"""Unit tests for BYODS service helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.byods.service import DuplicateDataSourceURLError, create_data_source, url_exists
from webex_byova.models.datasource import DataSourceCreate


@pytest.mark.asyncio
async def test_url_exists_matches_list_extra():
    client = MagicMock()
    item = MagicMock()
    item.__pydantic_extra__ = {"url": "https://example.com/grpc"}
    client.data_sources.alist = AsyncMock(return_value=[item])

    assert await url_exists(client, "https://example.com/grpc") is True
    client.data_sources.aget.assert_not_called()


@pytest.mark.asyncio
async def test_url_exists_resolves_by_id():
    client = MagicMock()
    item = MagicMock()
    item.__pydantic_extra__ = {"id": "ds-1"}
    detail = MagicMock(url="https://example.com/grpc")
    client.data_sources.alist = AsyncMock(return_value=[item])
    client.data_sources.aget = AsyncMock(return_value=detail)

    assert await url_exists(client, "https://example.com/grpc") is True


@pytest.mark.asyncio
async def test_create_data_source_rejects_duplicate_url():
    sdk = MagicMock()
    client = MagicMock()
    sdk.aget_client_for_org = AsyncMock(return_value=client)
    item = MagicMock()
    item.__pydantic_extra__ = {"url": "https://example.com/grpc"}
    client.data_sources.alist = AsyncMock(return_value=[item])

    payload = DataSourceCreate(
        schema_id="5397013b-7920-4ffc-807c-e8a3e0a18f43",
        url="https://example.com/grpc",
        audience="BYOVAGateway",
        subject="callAudioData",
        nonce="n1",
        token_lifetime_minutes=1440,
    )

    with pytest.raises(DuplicateDataSourceURLError):
        await create_data_source(sdk, "org-1", payload)
