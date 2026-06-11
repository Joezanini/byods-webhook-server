"""One-time local setup: Integration OAuth and serviceApp webhook registration."""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv
from webex_byova import BYOVA

load_dotenv()


async def main() -> None:
    sdk = BYOVA.from_env()

    print("Opening browser for Integration OAuth (developer authorization)...")
    tokens = await sdk.integration.aauthorize(open_browser=True)
    print("Integration authorized.")
    print("Access token:", tokens.access_token[:20] + "...")
    if tokens.refresh_token:
        print()
        print("Copy this refresh token into Render as WEBEX_INTEGRATION_REFRESH_TOKEN:")
        print(tokens.refresh_token)
    print("Expires at:", tokens.expires_at)

    target = os.environ.get("WEBEX_WEBHOOK_TARGET_URL")
    if target:
        created = await sdk.webhooks.aensure_service_app_webhooks(target)
        print(f"\nRegistered {len(created)} webhook(s) -> {target}")
    else:
        print(
            "\nSet WEBEX_WEBHOOK_TARGET_URL to your Render HTTPS URL "
            "(e.g. https://byods-webhook-server.onrender.com/webhooks/webex) "
            "and re-run to register webhooks.",
            file=sys.stderr,
        )

    await sdk.aclose()


if __name__ == "__main__":
    asyncio.run(main())
