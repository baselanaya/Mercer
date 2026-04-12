"""Request-logging and per-IP rate-limiting middleware.

RequestLoggingMiddleware — logs method, path, status, latency_ms via structlog.
RateLimitMiddleware     — 10 requests / 60 s per client IP using an in-memory
                          sliding window (good enough for single-process Phase 4).
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.logging import get_logger

_logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, HTTP status, and wall-clock latency."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        """Process each request, logging method, path, status, and latency."""
        start = time.perf_counter()
        response: Response = await call_next(request)  # type: ignore[operator]
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        _logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
            client=request.client.host if request.client else "unknown",
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter — ``max_requests`` per ``window_seconds`` per IP.

    Uses a per-IP ``deque`` of monotonic timestamps.  Expired entries are pruned
    on every request so memory stays bounded to (max_requests × num_active_ips).
    """

    def __init__(
        self,
        app: object,
        *,
        max_requests: int = 10,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._max = max_requests
        self._window = window_seconds
        self._buckets: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: object) -> Response:
        """Enforce per-IP rate limit; return 429 when the client exceeds the window."""
        ip = request.client.host if request.client else "unknown"

        # Localhost is never rate-limited (dev server + internal health checks)
        if ip in ("127.0.0.1", "::1"):
            return await call_next(request)  # type: ignore[operator,no-any-return]

        now = time.monotonic()
        cutoff = now - self._window

        bucket = self._buckets[ip]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= self._max:
            _logger.warning("rate_limit_exceeded", ip=ip)
            return JSONResponse(
                {"detail": "Rate limit exceeded. Please retry in a minute."},
                status_code=429,
            )

        bucket.append(now)
        return await call_next(request)  # type: ignore[operator,no-any-return]
