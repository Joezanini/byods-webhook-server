"""BYODS data source operations via webex-byova SDK."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from webex_byova import BYOVA
from webex_byova.exceptions import OrgNotRegisteredError
from webex_byova.models.datasource import DataSource, DataSourceCreate, DataSourceUpdate
from webex_byova.resources.datasource import OrgClient

from src.byods.models import DataSourceListItem, Schema
from src.config.settings import Settings, get_settings

if TYPE_CHECKING:
    pass


class DuplicateDataSourceURLError(Exception):
    """Raised when a data source URL is already registered for an org."""


async def url_exists(client: OrgClient, url: str) -> bool:
    """Return True if the org already has a data source with the given URL."""
    for item in await client.data_sources.alist():
        extra = item.__pydantic_extra__ or {}
        if extra.get("url") == url:
            return True
        item_id = extra.get("id")
        if item_id:
            detail = await client.data_sources.aget(str(item_id))
            if detail.url == url:
                return True
    return False


async def list_data_sources(sdk: BYOVA, org_id: str) -> list[DataSourceListItem]:
    client = await sdk.aget_client_for_org(org_id)
    return await client.data_sources.alist()


async def get_data_source(sdk: BYOVA, org_id: str, data_source_id: str) -> DataSource:
    client = await sdk.aget_client_for_org(org_id)
    return await client.data_sources.aget(data_source_id)


async def create_data_source(
    sdk: BYOVA,
    org_id: str,
    payload: DataSourceCreate,
    *,
    settings: Settings | None = None,
    skip_duplicate_check: bool = False,
) -> DataSource:
    client = await sdk.aget_client_for_org(org_id)
    if not skip_duplicate_check and payload.url:
        if await url_exists(client, payload.url):
            raise DuplicateDataSourceURLError(
                f"URL already registered for org {org_id}: {payload.url}"
            )
    return await client.data_sources.acreate(payload)


async def update_data_source(
    sdk: BYOVA,
    org_id: str,
    data_source_id: str,
    payload: DataSourceUpdate,
) -> DataSource:
    client = await sdk.aget_client_for_org(org_id)
    return await client.data_sources.aupdate(data_source_id, payload)


async def delete_data_source(sdk: BYOVA, org_id: str, data_source_id: str) -> None:
    client = await sdk.aget_client_for_org(org_id)
    await client.data_sources.adelete(data_source_id)


async def list_schemas(sdk: BYOVA, org_id: str) -> list[Schema]:
    client = await sdk.aget_client_for_org(org_id)
    return await client.schemas.alist()


async def get_schema(sdk: BYOVA, org_id: str, schema_id: str) -> Schema:
    client = await sdk.aget_client_for_org(org_id)
    return await client.schemas.aget(schema_id)


def build_create_payload(
    *,
    url: str,
    settings: Settings | None = None,
    schema_id: str | None = None,
    audience: str | None = None,
    subject: str | None = None,
    token_lifetime_minutes: int | None = None,
    nonce: str | None = None,
) -> DataSourceCreate:
    """Build a DataSourceCreate payload using settings defaults."""
    cfg = settings or get_settings()
    return DataSourceCreate(
        schema_id=schema_id or cfg.datasource_schema_id,
        url=url,
        audience=audience or cfg.datasource_audience,
        subject=subject or cfg.datasource_subject,
        nonce=nonce or str(uuid.uuid4()),
        token_lifetime_minutes=token_lifetime_minutes or cfg.datasource_token_life_minutes,
    )


async def auto_register_for_org(
    sdk: BYOVA, org_id: str, settings: Settings | None = None
) -> DataSource | None:
    """Register a BYODS data source for an org when auto-register is enabled."""
    cfg = settings or get_settings()
    if not cfg.auto_register_datasource:
        return None

    datasource_url = cfg.build_datasource_url()
    if not datasource_url:
        return None

    client = await sdk.aget_client_for_org(org_id)
    if await url_exists(client, datasource_url):
        return None

    return await create_data_source(
        sdk,
        org_id,
        build_create_payload(url=datasource_url, settings=cfg),
        settings=cfg,
        skip_duplicate_check=True,
    )


__all__ = [
    "DuplicateDataSourceURLError",
    "OrgNotRegisteredError",
    "url_exists",
    "list_data_sources",
    "get_data_source",
    "create_data_source",
    "update_data_source",
    "delete_data_source",
    "list_schemas",
    "get_schema",
    "build_create_payload",
    "auto_register_for_org",
]
