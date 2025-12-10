"""
HTTP access log_helper middleware for request tracing.
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastmcp import FastMCP

from server.config import config

log = logging.getLogger("fabric.mcp")


async def access_log_middleware(request: Request, call_next):
    """
    Middleware that adds HTTP request/response log_helper with request ID tracing.

    Generates or extracts a request ID from headers for distributed tracing,
    logs request completion with timing information, and adds the request ID
    to response headers.

    Args:
        request: The incoming HTTP request
        call_next: The next middleware/handler in the chain

    Returns:
        The HTTP response with x-request-id header added
    """
    # Generate or extract request ID for tracing through the system
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    try:
        response = await call_next(request)
        status = getattr(response, "status_code", 0)
    except Exception:
        status = 500
        log.exception("Unhandled exception during request",
                      extra={"request_id": rid, "path": request.url.path, "method": request.method})
        raise
    finally:
        # Log request completion with timing information
        dur_ms = round((time.perf_counter() - start) * 1000, 2)
        if config.uvicorn_access_log:
            log.info("HTTP %s %s -> %s in %.2fms",
                     request.method, request.url.path, status, dur_ms,
                     extra={
                         "request_id": rid,
                         "path": request.url.path,
                         "method": request.method,
                         "status": status,
                         "duration_ms": dur_ms,
                         "client": request.client.host if request.client else None,
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
