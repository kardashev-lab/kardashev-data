"""Simple per-IP rate limiting middleware."""
from __future__ import annotations

import os
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 120):
        super().__init__(app)
        self.rpm = requests_per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip = forwarded.split(",")[0].strip()

        now = time.time()
        window = [t for t in self._hits[ip] if now - t < 60]
        if len(window) >= self.rpm:
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)
        window.append(now)
        self._hits[ip] = window

        return await call_next(request)


def requests_per_minute() -> int:
    return int(os.environ.get("RATE_LIMIT_RPM", "120"))
