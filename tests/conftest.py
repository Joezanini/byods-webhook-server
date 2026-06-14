"""Shared pytest fixtures."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

# Minimal env for app import without real Webex credentials
os.environ.setdefault("WEBEX_INTEGRATION_CLIENT_ID", "test-integration-id")
os.environ.setdefault("WEBEX_INTEGRATION_CLIENT_SECRET", "test-integration-secret")
os.environ.setdefault("WEBEX_SA_CLIENT_ID", "test-sa-id")
os.environ.setdefault("WEBEX_SA_CLIENT_SECRET", "test-sa-secret")
os.environ.setdefault("WEBEX_MEDIA_ENABLED", "false")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
