"""HTTP middleware for request IDs and optional rate limiting."""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID to each HTTP request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class WebhookRateLimitMiddleware(BaseHTTPMiddleware):
    """Simple per-IP rate limit for POST /webhooks/webex."""

    def __init__(self, app, *, limit_per_minute: int) -> None:
        super().__init__(app)
        self._limit = limit_per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method != "POST" or request.url.path != "/webhooks/webex":
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - 60.0
        self._hits[client] = [t for t in self._hits[client] if t >= window_start]

        if len(self._hits[client]) >= self._limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )

        self._hits[client].append(now)
        return await call_next(request)
