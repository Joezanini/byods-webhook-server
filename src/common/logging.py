"""Structured logging configuration."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class StructuredJsonFormatter(logging.Formatter):
    """Emit JSON log lines with org_id, operation, and outcome when provided."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "org_id",
            "operation",
            "outcome",
            "request_id",
            "conversation_id",
            "session_id",
            "agent_count",
            "tracking_id",
            "agent_names",
            "virtual_agent_id",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(*, use_json: bool = True, level: int = logging.INFO) -> None:
    """Configure root logging for the application."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler()
    if use_json:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root.addHandler(handler)


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    org_id: str | None = None,
    operation: str | None = None,
    outcome: str | None = None,
    request_id: str | None = None,
    conversation_id: str | None = None,
    session_id: str | None = None,
    agent_count: int | None = None,
    tracking_id: str | None = None,
    agent_names: list[str] | None = None,
    virtual_agent_id: str | None = None,
) -> None:
    """Log with structured extra fields."""
    logger.log(
        level,
        message,
        extra={
            "org_id": org_id,
            "operation": operation,
            "outcome": outcome,
            "request_id": request_id,
            "conversation_id": conversation_id,
            "session_id": session_id,
            "agent_count": agent_count,
            "tracking_id": tracking_id,
            "agent_names": agent_names,
            "virtual_agent_id": virtual_agent_id,
        },
    )
