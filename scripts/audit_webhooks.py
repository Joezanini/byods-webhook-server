#!/usr/bin/env python3
"""CLI to list recent service app lifecycle audit events."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime

from dotenv import load_dotenv

from src.config.settings import get_settings
from src.persistence.audit_repository import create_audit_repository

load_dotenv()

EXIT_OK = 0
EXIT_ERROR = 1


async def cmd_list(org_id: str, limit: int, since: str | None) -> int:
    repo = create_audit_repository(get_settings())
    since_dt = datetime.fromisoformat(since) if since else None
    try:
        events = await repo.list_events(org_id, limit=limit, since=since_dt)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    for event in events:
        print(json.dumps(event, default=str))
    return EXIT_OK


def main() -> None:
    parser = argparse.ArgumentParser(description="List service app lifecycle audit events")
    sub = parser.add_subparsers(dest="command", required=True)
    list_p = sub.add_parser("list", help="List audit events for an org")
    list_p.add_argument("--org-id", required=True)
    list_p.add_argument("--limit", type=int, default=20)
    list_p.add_argument("--since", help="ISO8601 timestamp lower bound")

    args = parser.parse_args()
    if args.command == "list":
        raise SystemExit(asyncio.run(cmd_list(args.org_id, args.limit, args.since)))


if __name__ == "__main__":
    main()
