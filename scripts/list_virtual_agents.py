"""Probe ListVirtualAgents the same way Flow Designer does via gRPC."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import grpc
from dotenv import load_dotenv
from webex_byova import BYOVA
from webex_byova.media._internal.generated import byova_common_pb2, voicevirtualagent_pb2_grpc

from src.byods.service import list_data_sources
from src.config.settings import get_settings

load_dotenv()

EXIT_OK = 0
EXIT_ERROR = 1


@dataclass(frozen=True)
class GrpcTarget:
    """Resolved gRPC dial target."""

    address: str
    use_tls: bool
    authority: str | None = None


def _parse_target(raw: str) -> GrpcTarget:
    if "://" in raw:
        parsed = urlparse(raw)
        if not parsed.hostname:
            raise ValueError(f"Invalid target URL: {raw}")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        use_tls = parsed.scheme == "https"
        return GrpcTarget(
            address=f"{parsed.hostname}:{port}",
            use_tls=use_tls,
            authority=parsed.hostname,
        )

    if ":" not in raw:
        raw = f"{raw}:50051"
    return GrpcTarget(address=raw, use_tls=False)


def _default_target() -> str:
    settings = get_settings()
    datasource_url = settings.build_datasource_url()
    if datasource_url:
        return datasource_url

    port = os.environ.get("WEBEX_MEDIA_PORT", "50051")
    return f"localhost:{port}"


async def _fetch_bearer_token(org_id: str) -> str:
    refresh_token = os.environ.get("WEBEX_INTEGRATION_REFRESH_TOKEN")
    if not refresh_token:
        print(
            "WEBEX_INTEGRATION_REFRESH_TOKEN is required to fetch a datasource JWS token",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_ERROR)

    sdk = BYOVA.from_env()
    try:
        await sdk.integration.arefresh(refresh_token)
        await sdk.service_app.afetch_token_for_org(org_id)
        items = await list_data_sources(sdk, org_id)
        if not items:
            print(f"No data sources registered for org {org_id}", file=sys.stderr)
            raise SystemExit(EXIT_ERROR)

        token = items[0].model_dump(by_alias=True).get("jwsToken")
        if not token:
            print("Data source list response did not include jwsToken", file=sys.stderr)
            raise SystemExit(EXIT_ERROR)
        return str(token)
    finally:
        await sdk.aclose()


def _build_channel(target: GrpcTarget, *, insecure_tls: bool) -> grpc.aio.Channel:
    if target.use_tls:
        creds = grpc.ssl_channel_credentials()
        options: tuple[tuple[str, str], ...] = ()
        if target.authority:
            options = (("grpc.ssl_target_name_override", target.authority),)
        if insecure_tls:
            options = options + (("grpc.default_authority", target.authority or target.address),)
        return grpc.aio.secure_channel(target.address, creds, options=options)

    return grpc.aio.insecure_channel(target.address)


def _response_to_dict(response: Any) -> dict[str, Any]:
    agents = []
    for agent in response.virtual_agents:
        agents.append(
            {
                "virtualAgentId": agent.virtual_agent_id,
                "virtualAgentName": agent.virtual_agent_name,
                "isDefault": agent.is_default,
            }
        )
    return {"virtualAgents": agents}


async def list_virtual_agents(args: argparse.Namespace) -> int:
    target = _parse_target(args.target)
    metadata: list[tuple[str, str]] = []

    if args.tracking_id:
        metadata.append(("trackingid", args.tracking_id))

    bearer = args.bearer_token
    if bearer is None and args.org_id and not args.skip_auth:
        bearer = await _fetch_bearer_token(args.org_id)
    if bearer:
        metadata.append(("authorization", f"Bearer {bearer}"))

    request = byova_common_pb2.ListVARequest(
        customer_org_id=args.org_id or "",
        is_default_virtual_agent_enabled=args.default_agents,
    )

    channel = _build_channel(target, insecure_tls=args.insecure_tls)
    stub = voicevirtualagent_pb2_grpc.VoiceVirtualAgentStub(channel)

    try:
        response = await stub.ListVirtualAgents(
            request,
            metadata=metadata or None,
            timeout=args.timeout,
        )
    except grpc.aio.AioRpcError as exc:
        print(
            f"gRPC ListVirtualAgents failed: {exc.code().name} — {exc.details()}",
            file=sys.stderr,
        )
        if exc.code() == grpc.StatusCode.UNKNOWN and "authorization" in (exc.details() or "").lower():
            print(
                "Hint: pass --org-id to fetch a datasource JWS token, "
                "or set WEBEX_MEDIA_VERIFY_TOKENS=false for local plaintext probing.",
                file=sys.stderr,
            )
        return EXIT_ERROR
    finally:
        await channel.close()

    payload = _response_to_dict(response)
    print(json.dumps(payload, indent=2))
    print(
        f"\nListed {len(response.virtual_agents)} virtual agent(s) from {args.target}",
        file=sys.stderr,
    )
    return EXIT_OK


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Call VoiceVirtualAgent/ListVirtualAgents over gRPC, "
            "matching Flow Designer's virtual agent picker discovery."
        )
    )
    parser.add_argument(
        "--target",
        default=_default_target(),
        help=(
            "gRPC endpoint as host:port or https URL "
            "(default: datasource URL from env, else localhost:WEBEX_MEDIA_PORT)"
        ),
    )
    parser.add_argument(
        "--org-id",
        help="customer_org_id sent in ListVARequest; also used to fetch a datasource JWS token",
    )
    parser.add_argument(
        "--bearer-token",
        help="Authorization bearer token (JWS). Skips datasource token lookup.",
    )
    parser.add_argument(
        "--tracking-id",
        default=f"flow-designer-probe-{uuid.uuid4()}",
        help="trackingid gRPC metadata header (Flow Designer sends this)",
    )
    parser.add_argument(
        "--default-agents",
        action="store_true",
        help="Set is_default_virtual_agent_enabled on the request",
    )
    parser.add_argument(
        "--skip-auth",
        action="store_true",
        help="Do not send authorization metadata (works when WEBEX_MEDIA_VERIFY_TOKENS=false)",
    )
    parser.add_argument(
        "--insecure-tls",
        action="store_true",
        help="Use TLS without custom certificate verification (dev tunnels)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="RPC timeout in seconds (default: 15)",
    )

    args = parser.parse_args()
    raise SystemExit(asyncio.run(list_virtual_agents(args)))


if __name__ == "__main__":
    main()
