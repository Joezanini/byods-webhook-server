"""Integration smoke test for ListVirtualAgents gRPC discovery."""

from __future__ import annotations

import grpc
import pytest

from webex_byova.media._internal.generated import byova_common_pb2, voicevirtualagent_pb2_grpc

from src.byova.lifecycle import start_media_server, stop_media_server
from src.byova.server import create_media_server
from src.config.settings import Settings
from src.persistence.catalog_repository import create_catalog_repository


def _test_settings() -> Settings:
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


@pytest.mark.asyncio
async def test_list_virtual_agents_returns_six_agents(monkeypatch):
    """ListVirtualAgents returns the configured catalog over gRPC."""
    monkeypatch.setenv("WEBEX_MEDIA_PORT", "0")
    monkeypatch.setenv("WEBEX_MEDIA_VERIFY_TOKENS", "false")
    monkeypatch.setenv("WEBEX_VIRTUAL_AGENTS_CONFIG", "config/virtual_agents.json")

    settings = _test_settings()
    catalog_repo = create_catalog_repository(settings)
    server = await create_media_server(settings, catalog_repo)
    await start_media_server(server, settings)
    port = server.config.port

    try:
        channel = grpc.aio.insecure_channel(f"localhost:{port}")
        stub = voicevirtualagent_pb2_grpc.VoiceVirtualAgentStub(channel)
        response = await stub.ListVirtualAgents(byova_common_pb2.ListVARequest())

        assert len(response.virtual_agents) == 6
        names = {agent.virtual_agent_name for agent in response.virtual_agents}
        assert "Travel Booking Agent" in names
        assert "Scripted Agent" in names
        ids = {agent.virtual_agent_id for agent in response.virtual_agents}
        assert "1" in ids
        assert "6" in ids
    finally:
        await stop_media_server(server)
