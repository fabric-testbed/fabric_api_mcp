"""
HTTP metrics middleware for Prometheus instrumentation.

Tracks request count, latency, in-progress gauge, and per-user counters.
"""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fabric_api_mcp.auth.token import decode_token_claims, extract_bearer_token
from fabric_api_mcp.metrics import (
    mcp_http_request_duration_seconds,
    mcp_http_requests_in_progress,
    mcp_http_requests_total,
    mcp_requests_by_user_path_total,
    mcp_requests_by_user_total,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that records Prometheus HTTP metrics."""

    async def dispatch(self, request: Request, call_next) -> Response:
        method = request.method
        path = request.url.path

        # Skip metrics endpoint itself to avoid self-referential inflation
        if path == "/metrics":
            return await call_next(request)

        mcp_http_requests_in_progress.labels(method=method).inc()
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception:
            raise
        finally:
            duration = time.perf_counter() - start
            mcp_http_requests_in_progress.labels(method=method).dec()
            mcp_http_request_duration_seconds.labels(method=method, path=path).observe(duration)
            mcp_http_requests_total.labels(method=method, path=path, status=str(status)).inc()

            # Per-user counters from JWT
            try:
                token = extract_bearer_token(dict(request.headers))
                if token:
                    claims = decode_token_claims(token)
                    user_sub = claims.get("sub", "")
                    if user_sub:
                        mcp_requests_by_user_total.labels(user_sub=user_sub).inc()
                        mcp_requests_by_user_path_total.labels(
                            user_sub=user_sub, method=method, path=path,
                        ).inc()
            except Exception:
                pass
