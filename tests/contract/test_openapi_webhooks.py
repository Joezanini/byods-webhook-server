"""Contract tests for webhook and health HTTP surfaces."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def openapi_spec():
    spec_path = (
        Path(__file__).resolve().parents[2]
        / "specs/001-byods-byova-spec/contracts/openapi.yaml"
    )
    with spec_path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_openapi_defines_required_paths(openapi_spec):
    paths = openapi_spec["paths"]
    assert "/health" in paths
    assert "/ready" in paths
    assert "/webhooks/webex" in paths


@pytest.mark.asyncio
async def test_webhook_invalid_payload_returns_400(client, monkeypatch):
    from webex_byova.exceptions import ValidationError

    from src.webhooks import routes

    class FakeSdk:
        async def ahandle_service_app_webhook(self, payload):
            raise ValidationError("Unexpected webhook resource: unknown")

    routes.set_sdk(FakeSdk())

    response = await client.post("/webhooks/webex", json={"resource": "unknown"})
    assert response.status_code == 400
    assert "detail" in response.json()
