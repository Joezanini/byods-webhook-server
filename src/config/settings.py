"""Environment-driven application settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_DATASOURCE_SCHEMA_ID = "5397013b-7920-4ffc-807c-e8a3e0a18f43"
DEFAULT_DATASOURCE_PATH_SUFFIX = "/grpc"
DEFAULT_DATASOURCE_AUDIENCE = "BYOVAGateway"
DEFAULT_DATASOURCE_SUBJECT = "callAudioData"
DEFAULT_DATASOURCE_TOKEN_LIFE_MINUTES = 1440


@dataclass(frozen=True)
class Settings:
    """Application configuration loaded from environment variables."""

    port: int
    auto_register_datasource: bool
    datasource_public_url: str | None
    webhook_target_url: str | None
    datasource_path_suffix: str
    datasource_schema_id: str
    datasource_audience: str
    datasource_subject: str
    datasource_token_life_minutes: int
    integration_refresh_token: str | None
    integration_redirect_uri: str | None
    rate_limit_per_minute: int | None
    media_echo_enabled: bool
    media_enabled: bool
    log_json: bool
    virtual_agents_config_path: str
    persistence_backend: str
    dynamodb_table_name: str
    persistence_encryption_key: str | None
    persistence_audit_ttl_days: int
    aws_region: str
    aws_endpoint_url: str | None

    def build_datasource_url(self) -> str | None:
        """Derive BYODS ingestion URL from public URL or webhook target origin."""
        base = (self.datasource_public_url or self.webhook_target_url or "").strip()
        if not base:
            return None

        parsed = urlparse(base)
        if not parsed.scheme or not parsed.netloc:
            return None

        suffix = self.datasource_path_suffix.strip()
        if not suffix.startswith("/"):
            suffix = f"/{suffix}"

        return f"{parsed.scheme}://{parsed.netloc}{suffix}"

    @property
    def integration_redirect_path(self) -> str:
        """URL path for the Integration OAuth callback route."""
        raw = (self.integration_redirect_uri or "").strip()
        if not raw:
            return "/oauth/webex/callback"
        parsed = urlparse(raw)
        path = parsed.path or "/oauth/webex/callback"
        return path if path.startswith("/") else f"/{path}"

    @property
    def mount_oauth_callback(self) -> bool:
        """Mount production OAuth callback on FastAPI when redirect URI is not localhost."""
        raw = (self.integration_redirect_uri or "").strip()
        if not raw:
            return False
        host = (urlparse(raw).hostname or "").lower()
        return host not in {"127.0.0.1", "localhost", "::1"}


@lru_cache
def get_settings() -> Settings:
    """Load and cache settings from the environment."""
    rate_raw = os.environ.get("RATE_LIMIT_PER_MINUTE", "").strip()
    rate_limit = int(rate_raw) if rate_raw else None

    return Settings(
        port=int(os.environ.get("PORT", "8000")),
        auto_register_datasource=_env_bool("WEBEX_AUTO_REGISTER_DATASOURCE", default=True),
        datasource_public_url=os.environ.get("WEBEX_DATASOURCE_PUBLIC_URL"),
        webhook_target_url=os.environ.get("WEBEX_WEBHOOK_TARGET_URL"),
        datasource_path_suffix=os.environ.get(
            "WEBEX_DATASOURCE_PATH_SUFFIX", DEFAULT_DATASOURCE_PATH_SUFFIX
        ),
        datasource_schema_id=os.environ.get(
            "WEBEX_DATASOURCE_SCHEMA_ID", DEFAULT_DATASOURCE_SCHEMA_ID
        ),
        datasource_audience=os.environ.get(
            "WEBEX_DATASOURCE_AUDIENCE", DEFAULT_DATASOURCE_AUDIENCE
        ),
        datasource_subject=os.environ.get(
            "WEBEX_DATASOURCE_SUBJECT", DEFAULT_DATASOURCE_SUBJECT
        ),
        datasource_token_life_minutes=int(
            os.environ.get(
                "WEBEX_DATASOURCE_TOKEN_LIFE_MINUTES",
                str(DEFAULT_DATASOURCE_TOKEN_LIFE_MINUTES),
            )
        ),
        integration_refresh_token=os.environ.get("WEBEX_INTEGRATION_REFRESH_TOKEN"),
        integration_redirect_uri=os.environ.get("WEBEX_INTEGRATION_REDIRECT_URI"),
        rate_limit_per_minute=rate_limit,
        media_echo_enabled=_env_bool("WEBEX_MEDIA_ECHO_ENABLED", default=False),
        media_enabled=_env_bool("WEBEX_MEDIA_ENABLED", default=True),
        log_json=_env_bool("LOG_JSON", default=True),
        virtual_agents_config_path=os.environ.get(
            "WEBEX_VIRTUAL_AGENTS_CONFIG", "config/virtual_agents.json"
        ),
        persistence_backend=os.environ.get("PERSISTENCE_BACKEND", "memory").strip().lower(),
        dynamodb_table_name=os.environ.get("DYNAMODB_TABLE_NAME", "byods-app-state"),
        persistence_encryption_key=os.environ.get("PERSISTENCE_ENCRYPTION_KEY") or None,
        persistence_audit_ttl_days=int(os.environ.get("PERSISTENCE_AUDIT_TTL_DAYS", "30")),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        aws_endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None,
    )
