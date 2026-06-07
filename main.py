"""FastAPI webhook receiver for Webex serviceApp authorized/deauthorized events."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from webex_byova import BYOVA
from webex_byova.exceptions import AuthenticationError, ValidationError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("byods-webhook-server")

sdk = BYOVA.from_env()


@asynccontextmanager
async def lifespan(app: FastAPI):
    refresh_token = os.environ.get("WEBEX_INTEGRATION_REFRESH_TOKEN")
    if refresh_token:
        try:
            tokens = await sdk.integration.arefresh(refresh_token)
            logger.info(
                "Integration tokens bootstrapped from WEBEX_INTEGRATION_REFRESH_TOKEN "
                "(expires at %s)",
                tokens.expires_at,
            )
        except AuthenticationError as exc:
            logger.error("Failed to bootstrap Integration tokens: %s", exc)
            raise
    else:
        logger.warning(
            "WEBEX_INTEGRATION_REFRESH_TOKEN is not set; "
            "authorized webhooks will fail until Integration tokens are available"
        )

    yield

    await sdk.aclose()


app = FastAPI(
    title="BYODS Webhook Server",
    description="Receives Webex serviceApp authorized/deauthorized webhooks for BYOVA testing.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/webex")
async def webex_webhook(request: Request) -> dict[str, Any]:
    payload = await request.json()

    try:
        result = await sdk.ahandle_service_app_webhook(payload)
    except ValidationError as exc:
        logger.warning("Rejected webhook payload: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AuthenticationError as exc:
        logger.error("Authentication error handling webhook: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Integration not authorized; check WEBEX_INTEGRATION_REFRESH_TOKEN",
        ) from exc

    if result.event == "authorized":
        logger.info(
            "serviceApp authorized: org_id=%s access_token=%s... expires_in=%s",
            result.org_id,
            result.tokens.access_token[:12],
            result.tokens.expires_in,
        )
    elif result.event == "deauthorized":
        logger.info("serviceApp deauthorized: org_id=%s", result.org_id)

    return {"status": "ok", "org_id": result.org_id, "event": result.event}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
