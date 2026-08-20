"""
HTTP access log_helper middleware for request tracing.
"""
from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from fabric_mcp_common.integrations.starlette import client_ip, request_claims

from fabric_api_mcp.config import config

log = logging.getLogger("fabric.mcp")


class AccessLogMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that adds HTTP request/response logging with request ID tracing.

    Generates or extracts a request ID from headers for distributed tracing,
    logs request completion with timing information including user identity
    and client IP, and adds the request ID to response headers.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate or extract request ID for tracing through the system
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]

        # Extract user identity from JWT for logging.  request_claims() caches
        # the decode on request.state, so downstream middleware reuses it.
        ip = client_ip(request)
        claims = request_claims(request)
        user_sub = claims.sub or ""
        user_email = claims.email or ""

        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = getattr(response, "status_code", 0)
        except Exception:
            status = 500
            log.exception("Unhandled exception during request",
                          extra={"request_id": rid, "path": request.url.path, "method": request.method,
                                 "user_sub": user_sub, "user_email": user_email, "client_ip": ip})
            raise
        finally:
            # Log request completion with timing information
            dur_ms = round((time.perf_counter() - start) * 1000, 2)
            if config.uvicorn_access_log:
                user_display = user_email or user_sub or "anonymous"
                log.info("HTTP %s %s -> %s in %.2fms (user=%s, ip=%s)",
                         request.method, request.url.path, status, dur_ms,
                         user_display, ip,
                         extra={
                             "request_id": rid,
                             "path": request.url.path,
                             "method": request.method,
                             "status": status,
                             "duration_ms": dur_ms,
                             "client": request.client.host if request.client else None,
                             "user_sub": user_sub,
                             "user_email": user_email,
                             "client_ip": ip,
                         })
        # Return request_id in response headers for client-side tracing
        response.headers["x-request-id"] = rid
        return response
