"""
Rate limiting middleware for server mode.

Uses SlowAPI (built on top of `limits`) to enforce per-user request rate limits.
The rate limit key is the JWT `sub` claim; falls back to client IP for
unauthenticated requests.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from fabric_api_mcp.auth.token import decode_token_claims, extract_bearer_token
from fabric_api_mcp.config import config

log = logging.getLogger("fabric.mcp")


def _rate_limit_key(request: Request) -> str:
    """
    Extract rate limit key from the request.

    Uses the JWT `sub` claim as the key for authenticated requests,
    falling back to client IP for unauthenticated requests.
    """
    token = extract_bearer_token(dict(request.headers))
    if token:
        claims = decode_token_claims(token)
        sub = claims.get("sub")
        if sub:
            return sub

    # Fall back to client IP
    ip = request.headers.get("x-real-ip")
    if ip:
        return ip
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a JSON error response when rate limit is exceeded."""
    key = _rate_limit_key(request)
    log.warning(
        "Rate limit exceeded: %s (key=%s, path=%s)",
        exc.detail,
        key,
        request.url.path,
    )

    # Record Prometheus rate limit metric (server mode only)
    try:
        if config.metrics_enabled:
            from fabric_api_mcp.metrics import mcp_rate_limit_hits_total
            token = extract_bearer_token(dict(request.headers))
            key_type = "user" if token else "ip"
            mcp_rate_limit_hits_total.labels(key_type=key_type).inc()
    except Exception:
        pass

    return JSONResponse(
        status_code=429,
        content={
            "error": "limit_exceeded",
            "details": f"Rate limit exceeded: {exc.detail}",
        },
    )


def register_rate_limiter(app: FastAPI) -> None:
    """
    Register the SlowAPI rate limiter on the FastAPI application.

    Applies the configured rate limit to all /mcp endpoints.
    """
    if not config.rate_limit_enabled:
        log.info("Rate limiting is disabled")
        return

    limiter = Limiter(
        key_func=_rate_limit_key,
        default_limits=[config.rate_limit],
    )
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    log.info("Rate limiting enabled: %s", config.rate_limit)
