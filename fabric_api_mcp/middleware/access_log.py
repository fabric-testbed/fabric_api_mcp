"""
HTTP access log_helper middleware for request tracing.
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastmcp import FastMCP

from fabric_api_mcp.auth.token import decode_token_claims, extract_bearer_token
from fabric_api_mcp.config import config

log = logging.getLogger("fabric.mcp")


def _get_client_ip(request: Request) -> str:
    """Extract client IP from X-Real-IP, X-Forwarded-For, or request.client."""
    ip = request.headers.get("x-real-ip")
    if ip:
        return ip
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def access_log_middleware(request: Request, call_next):
    """
    Middleware that adds HTTP request/response log_helper with request ID tracing.

    Generates or extracts a request ID from headers for distributed tracing,
    logs request completion with timing information including user identity
    and client IP, and adds the request ID to response headers.

    Args:
        request: The incoming HTTP request
        call_next: The next middleware/handler in the chain

    Returns:
        The HTTP response with x-request-id header added
    """
    # Generate or extract request ID for tracing through the system
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]

    # Extract user identity from JWT for logging
    client_ip = _get_client_ip(request)
    token = extract_bearer_token(dict(request.headers))
    claims = decode_token_claims(token) if token else {}
    user_sub = claims.get("sub", "")
    user_email = claims.get("email", "")

    start = time.perf_counter()
    try:
        response = await call_next(request)
        status = getattr(response, "status_code", 0)
    except Exception:
        status = 500
        log.exception("Unhandled exception during request",
                      extra={"request_id": rid, "path": request.url.path, "method": request.method,
                             "user_sub": user_sub, "user_email": user_email, "client_ip": client_ip})
        raise
    finally:
        # Log request completion with timing information
        dur_ms = round((time.perf_counter() - start) * 1000, 2)
        if config.uvicorn_access_log:
            user_display = user_email or user_sub or "anonymous"
            log.info("HTTP %s %s -> %s in %.2fms (user=%s, ip=%s)",
                     request.method, request.url.path, status, dur_ms,
                     user_display, client_ip,
                     extra={
                         "request_id": rid,
                         "path": request.url.path,
                         "method": request.method,
                         "status": status,
                         "duration_ms": dur_ms,
                         "client": request.client.host if request.client else None,
                         "user_sub": user_sub,
                         "user_email": user_email,
                         "client_ip": client_ip,
                     })
    # Return request_id in response headers for client-side tracing
    response.headers["x-request-id"] = rid
    return response


def register_middleware(mcp: FastMCP) -> None:
    """
    Register the access log middleware with the FastMCP application.

    Args:
        mcp: The FastMCP server instance
    """
    if hasattr(mcp, "app") and mcp.app:
        mcp.app.middleware("http")(access_log_middleware)
