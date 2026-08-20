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

from fabric_mcp_common.net import DEFAULT_FORWARDED_HEADERS
from fabric_mcp_common.integrations.starlette import client_ip, request_claims

from fabric_api_mcp.config import config

log = logging.getLogger("fabric.mcp")


def _rate_limit_key(request: Request) -> str:
    """
    Extract rate limit key from the request.

    Only inputs the caller cannot forge may decide the key, because the key *is*
    the bucket: anything a caller controls can be rotated to get a fresh bucket
    per request, which bypasses the limit entirely rather than merely skewing it.

    So the order is:

    1. The JWT ``sub``, but **only from a signature-verified token**. An
       unverified payload decode is attacker-controlled — a JWT payload can be
       base64-encoded by hand with no signing key — so ``sub`` is trusted here
       only when :attr:`TokenClaims.verified` says a signature was checked.
    2. The client IP, honouring proxy headers only when
       ``RATE_LIMIT_TRUST_PROXY_HEADERS`` says a trusted proxy overwrites them.
    3. SlowAPI's own remote-address resolution, as a last resort.

    Note:
        This server does not currently verify signatures — it forwards tokens to
        the orchestrator, which authenticates them — so in practice keying falls
        through to the client IP. Configuring a verifier (see
        ``fabric_mcp_common.auth.verify``) restores per-user limiting
        automatically, with no change here.
    """
    claims = request_claims(request)
    if claims.verified and claims.sub:
        return str(claims.sub)

    forwarded_headers = (
        DEFAULT_FORWARDED_HEADERS if config.rate_limit_trust_proxy_headers else ()
    )
    return client_ip(
        request,
        forwarded_headers=forwarded_headers,
        default=get_remote_address(request),
    )


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
            from fabric_mcp_common.metrics import mcp_rate_limit_hits_total
            # Label by what the key actually was: a `sub` claim, or the IP.
            key_type = "user" if request_claims(request).sub else "ip"
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
