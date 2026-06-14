"""Unit tests for BYOVA media handler registration."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable
from unittest.mock import MagicMock

import pytest

from src.byova.catalog import VirtualAgentCatalogEntry
from src.byova.events import ListVirtualAgentsEvent
from src.byova.handlers import register_handlers
from src.config.settings import Settings
from webex_byova.media.events import SessionStartEvent


class FakeMediaServer:
    """Minimal stand-in for BYOVAMediaServer handler registry."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._virtual_agent_catalog = [
            VirtualAgentCatalogEntry("1", "Travel Booking Agent"),
            VirtualAgentCatalogEntry("2", "Credit card service"),
        ]

    def on(self, event: str):
        def decorator(fn: Callable) -> Callable:
            self._handlers[event].append(fn)
            return fn

        return decorator


def _settings() -> Settings:
    return Settings(
        port=8000,
        auto_register_datasource=True,
        datasource_public_url=None,
        webhook_target_url=None,
        datasource_path_suffix="/grpc",
        datasource_schema_id="5397013b-7920-4ffc-807c-e8a3e0a18f43",
        datasource_audience="BYOVAGateway",
        datasource_subject="callAudioData",
        datasource_token_life_minutes=1440,
        integration_refresh_token=None,
        rate_limit_per_minute=None,
        media_echo_enabled=False,
        media_enabled=True,
        log_json=True,
        virtual_agents_config_path="config/virtual_agents.json",
        persistence_backend="memory",
        dynamodb_table_name="byods-app-state",
        persistence_encryption_key=None,
        persistence_audit_ttl_days=30,
        aws_region="us-east-1",
        aws_endpoint_url=None,
    )


def test_register_handlers_attaches_events():
    server = FakeMediaServer()
    register_handlers(server, _settings())

    for event in (
        "list_virtual_agents",
        "session_start",
        "turn_started",
        "audio_input",
        "turn_ended",
        "session_end",
        "error",
    ):
        assert server._handlers.get(event), f"missing handler for {event}"


@pytest.mark.asyncio
async def test_list_virtual_agents_handler_logs(caplog):
    server = FakeMediaServer()
    register_handlers(server, _settings())
    handler = server._handlers["list_virtual_agents"][0]

    event = ListVirtualAgentsEvent(
        customer_org_id="org-123",
        agent_count=2,
        agent_names=["Travel Booking Agent", "Credit card service"],
        tracking_id="track-abc",
    )

    with caplog.at_level(logging.INFO):
        await handler(event)

    assert "Flow Designer requested virtual agent list" in caplog.text
    assert "agents=2" in caplog.text
    assert "tracking_id=track-abc" in caplog.text


@pytest.mark.asyncio
async def test_session_start_logs_virtual_agent_id(caplog):
    server = FakeMediaServer()
    register_handlers(server, _settings())
    handler = server._handlers["session_start"][0]

    session = MagicMock()
    session.session_id = "sess-1"
    event = SessionStartEvent(
        conversation_id="conv-1",
        metadata={"virtual_agent_id": "1", "customer_org_id": "org-1"},
    )

    with caplog.at_level(logging.INFO):
        await handler(event, session)

    assert "virtual_agent_id=1" in caplog.text
    assert "customer_org_id=org-1" in caplog.text


@pytest.mark.asyncio
async def test_session_start_warns_on_unknown_agent_id(caplog):
    server = FakeMediaServer()
    register_handlers(server, _settings())
    handler = server._handlers["session_start"][0]

    session = MagicMock()
    session.session_id = "sess-2"
    event = SessionStartEvent(
        conversation_id="conv-2",
        metadata={"virtual_agent_id": "99"},
    )

    with caplog.at_level(logging.WARNING):
        await handler(event, session)

    assert "virtual_agent_id=99 not found in catalog" in caplog.text
