"""Shared DynamoDB table access (boto3 with async wrappers)."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def _table_resource(*, table_name: str, region: str, endpoint_url: str | None):
    kwargs: dict[str, Any] = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    dynamodb = boto3.resource("dynamodb", **kwargs)
    return dynamodb.Table(table_name)


async def _run(fn, *args, **kwargs):
    return await asyncio.to_thread(partial(fn, *args, **kwargs))


class DynamoDBTable:
    """Async-friendly wrapper around a boto3 Table."""

    def __init__(self, *, table_name: str, region: str, endpoint_url: str | None) -> None:
        self._table = _table_resource(
            table_name=table_name,
            region=region,
            endpoint_url=endpoint_url,
        )

    async def get_item(self, **kwargs):
        return await _run(self._table.get_item, **kwargs)

    async def put_item(self, **kwargs):
        return await _run(self._table.put_item, **kwargs)

    async def delete_item(self, **kwargs):
        return await _run(self._table.delete_item, **kwargs)

    async def query(self, **kwargs):
        return await _run(self._table.query, **kwargs)

    async def scan(self, **kwargs):
        return await _run(self._table.scan, **kwargs)


async def check_table_reachable(
    *,
    table_name: str,
    region: str,
    endpoint_url: str | None = None,
) -> bool:
    """Return True if the table responds to a lightweight read."""
    try:
        table = DynamoDBTable(
            table_name=table_name,
            region=region,
            endpoint_url=endpoint_url,
        )
        await table.get_item(Key={"PK": "CATALOG", "SK": "META"})
        return True
    except (ClientError, BotoCoreError, OSError):
        return False
