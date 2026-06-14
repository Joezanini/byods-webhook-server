"""FastAPI application for Webex BYODS webhooks and BYOVA media."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from webex_byova.exceptions import AuthenticationError
from src.common.logging import configure_logging
from src.common.middleware import RequestIdMiddleware, WebhookRateLimitMiddleware
from src.config.settings import get_settings
from src.persistence.client import check_table_reachable
from src.persistence.factory import create_persistence_resources, create_sdk
from src.webhooks.routes import router as webhooks_router, set_audit_repository, set_sdk
from src.webhooks.integration_bootstrap import (
    bootstrap_integration,
    ensure_service_app_webhooks_if_configured,
)
from src.webhooks.oauth_callback import register_oauth_callback_route, set_oauth_dependencies

load_dotenv()

logger = logging.getLogger("byods-webhook-server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(use_json=settings.log_json)

    persistence = await create_persistence_resources(settings)
    app.state.persistence = persistence
    set_audit_repository(persistence.audit_repository)

    sdk = create_sdk(settings, persistence.token_storage)
    set_sdk(sdk)
    set_oauth_dependencies(sdk, persistence.token_storage, settings)
    app.state.sdk = sdk

    integration_ready = await bootstrap_integration(
        sdk, settings, persistence.token_storage
    )
    app.state.integration_ready = integration_ready
    if not integration_ready:
        logger.warning(
            "Integration not ready; complete OAuth via callback URL or set "
            "WEBEX_INTEGRATION_REFRESH_TOKEN for bootstrap"
        )

    if integration_ready and settings.webhook_target_url:
        try:
            await ensure_service_app_webhooks_if_configured(sdk, settings)
        except AuthenticationError:
            app.state.integration_ready = False
            raise

    if settings.persistence_backend == "dynamodb":
        app.state.persistence_ready = await check_table_reachable(
            table_name=settings.dynamodb_table_name,
            region=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        )
        if not app.state.persistence_ready:
            logger.error(
                "DynamoDB table %s is not reachable",
                settings.dynamodb_table_name,
            )
    else:
        app.state.persistence_ready = True

    media_server = None
    if settings.media_enabled:
        from src.byova.lifecycle import start_media_server, stop_media_server
        from src.byova.server import create_media_server

        await persistence.catalog_repository.ensure_seeded(
            settings.virtual_agents_config_path
        )
        media_server = await create_media_server(settings, persistence.catalog_repository)
        await start_media_server(media_server, settings)
        app.state.media_server = media_server

    yield

    if media_server is not None:
        from src.byova.lifecycle import stop_media_server

        await stop_media_server(media_server)
    await sdk.aclose()
    await persistence.aclose()


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
    async def ready(request: Request) -> dict[str, str]:
        if not getattr(request.app.state, "integration_ready", False):
            raise HTTPException(
                status_code=503,
                detail="Integration credentials not bootstrapped",
            )
        if settings.persistence_backend == "dynamodb" and not getattr(
            request.app.state, "persistence_ready", False
        ):
            raise HTTPException(
                status_code=503,
                detail="DynamoDB persistence backend unavailable",
            )
        return {"status": "ok"}

    app.include_router(webhooks_router)
    if settings.mount_oauth_callback:
        register_oauth_callback_route(app, settings)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
