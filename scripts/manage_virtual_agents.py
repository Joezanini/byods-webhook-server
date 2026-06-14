#!/usr/bin/env python3
"""CLI for virtual agent catalog CRUD via DynamoDB persistence."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from dotenv import load_dotenv

from src.byova.catalog import CatalogLoadError, VirtualAgentCatalogEntry, validate_catalog_entries
from src.config.settings import get_settings
from src.persistence.catalog_repository import CatalogRepositoryError, create_catalog_repository

load_dotenv()

EXIT_OK = 0
EXIT_ERROR = 1


def _print_entries(entries: list[VirtualAgentCatalogEntry]) -> None:
    payload = [
        {
            "virtual_agent_id": e.virtual_agent_id,
            "virtual_agent_name": e.virtual_agent_name,
            "is_default": e.is_default,
        }
        for e in entries
    ]
    print(json.dumps(payload, indent=2))


async def cmd_list() -> int:
    repo = create_catalog_repository(get_settings())
    try:
        entries = await repo.list_agents()
        _print_entries(entries)
        return EXIT_OK
    except CatalogLoadError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR


async def cmd_add(agent_id: str, name: str, is_default: bool) -> int:
    repo = create_catalog_repository(get_settings())
    try:
        entries = await repo.list_agents()
        if any(e.virtual_agent_id == agent_id for e in entries):
            print(f"DUPLICATE_ID: agent id '{agent_id}' already exists", file=sys.stderr)
            return EXIT_ERROR
        if is_default:
            entries = [
                VirtualAgentCatalogEntry(
                    virtual_agent_id=e.virtual_agent_id,
                    virtual_agent_name=e.virtual_agent_name,
                    is_default=False,
                )
                for e in entries
            ]
        entries.append(
            VirtualAgentCatalogEntry(
                virtual_agent_id=agent_id,
                virtual_agent_name=name,
                is_default=is_default,
            )
        )
        validate_catalog_entries(entries)
        await repo.replace_all(entries)
        return EXIT_OK
    except (CatalogLoadError, CatalogRepositoryError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR


async def cmd_update(
    agent_id: str,
    name: str | None,
    is_default: bool | None,
) -> int:
    repo = create_catalog_repository(get_settings())
    try:
        entries = await repo.list_agents()
        found = False
        updated: list[VirtualAgentCatalogEntry] = []
        for entry in entries:
            if entry.virtual_agent_id != agent_id:
                updated.append(entry)
                continue
            found = True
            updated.append(
                VirtualAgentCatalogEntry(
                    virtual_agent_id=agent_id,
                    virtual_agent_name=name if name is not None else entry.virtual_agent_name,
                    is_default=is_default if is_default is not None else entry.is_default,
                )
            )
        if not found:
            print(f"NOT_FOUND: agent id '{agent_id}'", file=sys.stderr)
            return EXIT_ERROR
        if is_default:
            updated = [
                VirtualAgentCatalogEntry(
                    virtual_agent_id=e.virtual_agent_id,
                    virtual_agent_name=e.virtual_agent_name,
                    is_default=e.virtual_agent_id == agent_id,
                )
                for e in updated
            ]
        validate_catalog_entries(updated)
        await repo.replace_all(updated)
        return EXIT_OK
    except (CatalogLoadError, CatalogRepositoryError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR


async def cmd_remove(agent_id: str) -> int:
    repo = create_catalog_repository(get_settings())
    try:
        await repo.remove_agent(agent_id)
        return EXIT_OK
    except CatalogLoadError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    except CatalogRepositoryError as exc:
        if "not found" in str(exc).lower():
            print(f"NOT_FOUND: {exc}", file=sys.stderr)
        else:
            print(f"EMPTY_CATALOG: {exc}", file=sys.stderr)
        return EXIT_ERROR


async def cmd_set_default(agent_id: str) -> int:
    return await cmd_update(agent_id, name=None, is_default=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage virtual agent catalog")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List catalog entries")

    add_p = sub.add_parser("add", help="Add an agent")
    add_p.add_argument("--id", required=True, dest="agent_id")
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--default", action="store_true", dest="is_default")

    upd_p = sub.add_parser("update", help="Update an agent")
    upd_p.add_argument("--id", required=True, dest="agent_id")
    upd_p.add_argument("--name")
    upd_p.add_argument("--default", action="store_true", dest="is_default")

    rm_p = sub.add_parser("remove", help="Remove an agent")
    rm_p.add_argument("--id", required=True, dest="agent_id")

    sd_p = sub.add_parser("set-default", help="Set the default agent")
    sd_p.add_argument("--id", required=True, dest="agent_id")

    args = parser.parse_args()

    if args.command == "list":
        raise SystemExit(asyncio.run(cmd_list()))
    if args.command == "add":
        raise SystemExit(asyncio.run(cmd_add(args.agent_id, args.name, args.is_default)))
    if args.command == "update":
        raise SystemExit(
            asyncio.run(
                cmd_update(
                    args.agent_id,
                    args.name,
                    args.is_default if args.is_default else None,
                )
            )
        )
    if args.command == "remove":
        raise SystemExit(asyncio.run(cmd_remove(args.agent_id)))
    if args.command == "set-default":
        raise SystemExit(asyncio.run(cmd_set_default(args.agent_id)))


if __name__ == "__main__":
    main()
