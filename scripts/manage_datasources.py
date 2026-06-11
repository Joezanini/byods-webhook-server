"""CLI for BYODS data source CRUD via webex-byova SDK."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from webex_byova import BYOVA
from webex_byova.exceptions import AuthenticationError, NotFoundError, OrgNotRegisteredError, ValidationError
from webex_byova.models.datasource import DataSourceUpdate

from src.byods.service import (
    DuplicateDataSourceURLError,
    build_create_payload,
    create_data_source,
    delete_data_source,
    get_data_source,
    get_schema,
    list_data_sources,
    list_schemas,
    update_data_source,
)
from src.config.settings import get_settings

load_dotenv()

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_DUPLICATE = 2


def _print_json(data: object) -> None:
    if hasattr(data, "model_dump"):
        print(json.dumps(data.model_dump(by_alias=True), indent=2, default=str))
    else:
        print(json.dumps(data, indent=2, default=str))


async def _bootstrap_sdk(org_id: str) -> BYOVA:
    sdk = BYOVA.from_env()
    refresh_token = os.environ.get("WEBEX_INTEGRATION_REFRESH_TOKEN")
    if not refresh_token:
        print(
            "WEBEX_INTEGRATION_REFRESH_TOKEN is required",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_ERROR)

    await sdk.integration.arefresh(refresh_token)
    await sdk.service_app.afetch_token_for_org(org_id)
    return sdk


async def cmd_list(org_id: str) -> int:
    sdk = await _bootstrap_sdk(org_id)
    try:
        items = await list_data_sources(sdk, org_id)
        _print_json([item.model_dump(by_alias=True) for item in items])
        return EXIT_OK
    except OrgNotRegisteredError as exc:
        print(f"Org not authorized: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await sdk.aclose()


async def cmd_get(org_id: str, data_source_id: str) -> int:
    sdk = await _bootstrap_sdk(org_id)
    try:
        item = await get_data_source(sdk, org_id, data_source_id)
        _print_json(item)
        return EXIT_OK
    except OrgNotRegisteredError as exc:
        print(f"Org not authorized: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except NotFoundError as exc:
        print(f"Not found: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await sdk.aclose()


async def cmd_create(args: argparse.Namespace) -> int:
    settings = get_settings()
    url = args.url or settings.build_datasource_url()
    if not url:
        print("Provide --url or set WEBEX_WEBHOOK_TARGET_URL / WEBEX_DATASOURCE_PUBLIC_URL", file=sys.stderr)
        return EXIT_ERROR

    sdk = await _bootstrap_sdk(args.org_id)
    try:
        payload = build_create_payload(
            url=url,
            settings=settings,
            schema_id=args.schema_id,
            audience=args.audience,
            subject=args.subject,
            token_lifetime_minutes=args.token_lifetime_minutes,
        )
        created = await create_data_source(sdk, args.org_id, payload, settings=settings)
        _print_json(created)
        return EXIT_OK
    except DuplicateDataSourceURLError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_DUPLICATE
    except OrgNotRegisteredError as exc:
        print(f"Org not authorized: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (ValidationError, AuthenticationError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    finally:
        await sdk.aclose()


async def cmd_update(args: argparse.Namespace) -> int:
    sdk = await _bootstrap_sdk(args.org_id)
    try:
        payload = DataSourceUpdate(
            schema_id=args.schema_id,
            url=args.url,
            audience=args.audience,
            subject=args.subject,
            token_lifetime_minutes=args.token_lifetime_minutes,
        )
        updated = await update_data_source(sdk, args.org_id, args.id, payload)
        _print_json(updated)
        return EXIT_OK
    except OrgNotRegisteredError as exc:
        print(f"Org not authorized: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except NotFoundError as exc:
        print(f"Not found: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await sdk.aclose()


async def cmd_delete(org_id: str, data_source_id: str) -> int:
    sdk = await _bootstrap_sdk(org_id)
    try:
        await delete_data_source(sdk, org_id, data_source_id)
        return EXIT_OK
    except OrgNotRegisteredError as exc:
        print(f"Org not authorized: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except NotFoundError as exc:
        print(f"Not found: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await sdk.aclose()


async def cmd_schemas_list(org_id: str) -> int:
    sdk = await _bootstrap_sdk(org_id)
    try:
        items = await list_schemas(sdk, org_id)
        _print_json([item.model_dump(by_alias=True) for item in items])
        return EXIT_OK
    except OrgNotRegisteredError as exc:
        print(f"Org not authorized: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await sdk.aclose()


async def cmd_schemas_get(org_id: str, schema_id: str) -> int:
    sdk = await _bootstrap_sdk(org_id)
    try:
        item = await get_schema(sdk, org_id, schema_id)
        _print_json(item)
        return EXIT_OK
    except OrgNotRegisteredError as exc:
        print(f"Org not authorized: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except NotFoundError as exc:
        print(f"Not found: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await sdk.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage BYODS data sources via webex-byova SDK")
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="List data sources for an org")
    list_p.add_argument("--org-id", required=True)

    get_p = sub.add_parser("get", help="Get a data source by ID")
    get_p.add_argument("--org-id", required=True)
    get_p.add_argument("--id", required=True)

    create_p = sub.add_parser("create", help="Create a data source")
    create_p.add_argument("--org-id", required=True)
    create_p.add_argument("--url")
    create_p.add_argument("--schema-id")
    create_p.add_argument("--audience")
    create_p.add_argument("--subject")
    create_p.add_argument("--token-lifetime-minutes", type=int)

    update_p = sub.add_parser("update", help="Update a data source")
    update_p.add_argument("--org-id", required=True)
    update_p.add_argument("--id", required=True)
    update_p.add_argument("--url")
    update_p.add_argument("--schema-id")
    update_p.add_argument("--audience")
    update_p.add_argument("--subject")
    update_p.add_argument("--token-lifetime-minutes", type=int)

    delete_p = sub.add_parser("delete", help="Delete a data source")
    delete_p.add_argument("--org-id", required=True)
    delete_p.add_argument("--id", required=True)

    schemas_p = sub.add_parser("schemas", help="Schema operations")
    schemas_sub = schemas_p.add_subparsers(dest="schemas_command", required=True)

    schemas_list_p = schemas_sub.add_parser("list", help="List schemas")
    schemas_list_p.add_argument("--org-id", required=True)

    schemas_get_p = schemas_sub.add_parser("get", help="Get schema by ID")
    schemas_get_p.add_argument("--org-id", required=True)
    schemas_get_p.add_argument("--id", required=True)

    args = parser.parse_args()

    if args.command == "list":
        raise SystemExit(asyncio.run(cmd_list(args.org_id)))
    if args.command == "get":
        raise SystemExit(asyncio.run(cmd_get(args.org_id, args.id)))
    if args.command == "create":
        raise SystemExit(asyncio.run(cmd_create(args)))
    if args.command == "update":
        raise SystemExit(asyncio.run(cmd_update(args)))
    if args.command == "delete":
        raise SystemExit(asyncio.run(cmd_delete(args.org_id, args.id)))
    if args.command == "schemas" and args.schemas_command == "list":
        raise SystemExit(asyncio.run(cmd_schemas_list(args.org_id)))
    if args.command == "schemas" and args.schemas_command == "get":
        raise SystemExit(asyncio.run(cmd_schemas_get(args.org_id, args.id)))

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
