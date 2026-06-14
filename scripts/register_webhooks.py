"""One-time setup: Integration OAuth and serviceApp webhook registration."""

from __future__ import annotations

import asyncio
import os
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv
from webex_byova import BYOVA

load_dotenv()


def _is_local_redirect(redirect_uri: str) -> bool:
    host = (urlparse(redirect_uri).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


async def main() -> None:
    sdk = BYOVA.from_env()
    redirect_uri = os.environ.get(
        "WEBEX_INTEGRATION_REDIRECT_URI", "http://127.0.0.1:8765/callback"
    )

    if _is_local_redirect(redirect_uri):
        print("Opening browser for Integration OAuth (developer authorization)...")
        tokens = await sdk.integration.aauthorize(open_browser=True)
        print("Integration authorized.")
        print("Access token:", tokens.access_token[:20] + "...")
        if tokens.refresh_token:
            print()
            print("Copy this refresh token into deployment env as bootstrap (optional once DynamoDB has tokens):")
            print(tokens.refresh_token)
        print("Expires at:", tokens.expires_at)
    else:
        url, state = sdk.integration.get_authorization_url()
        print("Production redirect URI configured. Open this URL in a browser to authorize:")
        print()
        print(url)
        print()
        print(f"state: {state}")
        print()
        print(
            "After consent, Webex redirects to your deployed callback route. "
            "Tokens are persisted in DynamoDB when PERSISTENCE_BACKEND=dynamodb."
        )
        print(
            "Re-run this script after OAuth completes to verify webhooks, "
            "or rely on server startup webhook ensure."
        )

    target = os.environ.get("WEBEX_WEBHOOK_TARGET_URL")
    if target:
        created = await sdk.webhooks.aensure_service_app_webhooks(target)
        print(f"\nRegistered {len(created)} webhook(s) -> {target}")
    else:
        print(
            "\nSet WEBEX_WEBHOOK_TARGET_URL to your HTTPS webhook URL "
            "(e.g. https://byods-webhook-server.onrender.com/webhooks/webex) "
            "and re-run to register webhooks.",
            file=sys.stderr,
        )

    await sdk.aclose()


if __name__ == "__main__":
    asyncio.run(main())
