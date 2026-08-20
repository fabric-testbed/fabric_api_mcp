"""
Rate limiting middleware for server mode.

Uses SlowAPI (built on top of `limits`) to enforce per-user request rate limits.
The rate limit key is the JWT `sub` claim; falls back to client IP for
unauthenticated requests.
"""
from __future__ import annotations

import ipaddress
import logging
from typing import Optional

from fastapi import FastAPI
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from fabric_mcp_common.integrations.starlette import request_claims

from fabric_api_mcp.config import config

log = logging.getLogger("fabric.mcp")

#: Header a trusted proxy uses to assert the real client address. nginx sets
#: this from ``$remote_addr``, overwriting anything the client sent — unlike
#: ``X-Forwarded-For``, which it appends to.
TRUSTED_CLIENT_IP_HEADER = "x-real-ip"


def _is_trusted_proxy(host: Optional[str]) -> bool:
    """Whether *host* is one of the peers allowed to assert the client address."""
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    for entry in config.rate_limit_trusted_proxies:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            log.warning("Ignoring malformed RATE_LIMIT_TRUSTED_PROXIES entry: %s", entry)
    return False


def _rate_limit_key(request: Request) -> str:
    """
    Extract rate limit key from the request.

    Only inputs the caller cannot forge may decide the key, because the key *is*
    the bucket: anything a caller controls can be rotated for a fresh bucket per
    request, which bypasses the limit outright rather than merely skewing it.
    But the key must also actually distinguish callers — behind a proxy, keying
    on the socket peer puts everyone in one bucket and caps the whole service.

    Order:

    1. The JWT ``sub``, but **only from a signature-verified token**. An
       unverified payload decode is attacker-controlled — a JWT payload can be
       base64-encoded by hand with no signing key — so ``sub`` is trusted only
       when :attr:`TokenClaims.verified` says a signature was checked.
    2. ``X-Real-IP``, but **only when the socket peer is a trusted proxy**
       (``RATE_LIMIT_TRUSTED_PROXIES``). The peer cannot be forged by a remote
       client, so it is what makes the header believable.
    3. The socket peer itself, via SlowAPI's remote-address resolution.

    ``X-Forwarded-For`` is deliberately *not* consulted. The nginx in front of
    this service sets it with ``$proxy_add_x_forwarded_for``, which **appends**
    to whatever the client sent, so its left-most entry is caller-controlled
    even on a trusted hop. ``X-Real-IP`` is set to ``$remote_addr``, which
    overwrites, so it reflects the real peer of the proxy.

    Note:
        This server does not verify signatures — it forwards tokens to the
        orchestrator, which authenticates them — so keying is per client address
        in practice. Configuring a verifier (``fabric_mcp_common.auth.verify``)
        restores per-user keying with no change here.
    """
    claims = request_claims(request)
    if claims.verified and claims.sub:
        return str(claims.sub)

    peer = getattr(getattr(request, "client", None), "host", None)
    if _is_trusted_proxy(peer):
        asserted = request.headers.get(TRUSTED_CLIENT_IP_HEADER)
        if asserted:
            return asserted.strip()

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
