"""FastAPI application for Webex BYODS webhooks and BYOVA media."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from webex_byova import BYOVA
from webex_byova.exceptions import AuthenticationError
from src.common.logging import configure_logging
from src.common.middleware import RequestIdMiddleware, WebhookRateLimitMiddleware
from src.config.settings import get_settings
from src.webhooks.routes import router as webhooks_router, set_sdk

load_dotenv()

logger = logging.getLogger("byods-webhook-server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(use_json=settings.log_json)

    sdk = BYOVA.from_env()
    set_sdk(sdk)
    app.state.sdk = sdk

    refresh_token = settings.integration_refresh_token
    if refresh_token:
        try:
            tokens = await sdk.integration.arefresh(refresh_token)
            logger.info(
                "Integration tokens bootstrapped (expires at %s)",
                tokens.expires_at,
            )
            app.state.integration_ready = True
        except AuthenticationError as exc:
            logger.error("Failed to bootstrap Integration tokens: %s", exc)
            app.state.integration_ready = False
            raise
    else:
        logger.warning(
            "WEBEX_INTEGRATION_REFRESH_TOKEN is not set; "
            "authorized webhooks will fail until Integration tokens are available"
        )
        app.state.integration_ready = False

    media_server = None
    if settings.media_enabled:
        from src.byova.lifecycle import start_media_server, stop_media_server
        from src.byova.server import create_media_server

        media_server = create_media_server(settings)
        await start_media_server(media_server, settings)
        app.state.media_server = media_server

    yield

    if media_server is not None:
        from src.byova.lifecycle import stop_media_server

        await stop_media_server(media_server)
    await sdk.aclose()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="BYODS Webhook Server",
        description=(
            "Receives Webex serviceApp webhooks and hosts BYOVA gRPC media via webex-byova SDK."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    if settings.rate_limit_per_minute:
        app.add_middleware(
            WebhookRateLimitMiddleware,
            limit_per_minute=settings.rate_limit_per_minute,
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        if not getattr(app.state, "integration_ready", False):
            raise HTTPException(
                status_code=503,
                detail="Integration credentials not bootstrapped",
            )
        return {"status": "ok"}

    app.include_router(webhooks_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
