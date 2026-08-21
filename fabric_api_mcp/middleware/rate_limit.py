"""
Rate limiting middleware for server mode.

Uses SlowAPI (built on top of ``limits``). The key is derived only from inputs a
caller cannot forge — a signature-verified JWT ``sub``, else the address the
declared proxy asserts, else the socket peer — because the key *is* the bucket.
See :func:`_rate_limit_key` for the full ordering and why ``X-Forwarded-For`` is
excluded.

This server does not verify token signatures (it forwards them to the
orchestrator, which authenticates them), so limiting is per client address
rather than per user, and no setting changes that — see :func:`_rate_limit_key`
for what enabling per-user keying would actually take.
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

from fabric_mcp_common.integrations.starlette import request_claims, trusted_client_ip
from fabric_mcp_common.net import invalid_networks

from fabric_api_mcp.config import config

log = logging.getLogger("fabric.mcp")


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
        Step 1 does not fire today, and there is no setting that makes it. This
        server never verifies signatures — it forwards tokens to the
        orchestrator, which authenticates them — and ``request_claims()`` takes
        no verifier, so its claims are always ``verified=False``. Keying is
        therefore per client address. The check is kept so that adding
        verification later is safe by construction rather than another audit.

        Turning on per-user keying needs code, not configuration: install the
        ``fabric_mcp_common[verify]`` extra, build a ``CredMgrVerifier`` against
        ``FABRIC_CREDMGR_HOST``, and add a middleware that verifies the bearer
        token and stores the result on
        ``request.state.fabric_token_claims`` — the attribute
        ``request_claims()`` reads first, so a verified value there is what this
        function would then see. That puts a JWKS fetch and a signature check on
        the request path, which is why it is not done implicitly.
    """
    return _rate_limit_identity(request)[0]


def _rate_limit_identity(request: Request) -> tuple[str, str]:
    """The rate-limit key and what kind of thing it is (``user`` or ``ip``).

    Returned together so the ``key_type`` metric label cannot disagree with the
    key actually used. Deriving the label separately let a forged token report
    ``user`` for a request that was really bucketed by address.
    """
    claims = request_claims(request)
    # NOTE: request_claims() performs an unverified decode, so `verified` is
    # always False today and this branch never runs. If you wire a verifier —
    # see "Per-user limiting: what it would take" in the README — this starts
    # keying per user, and that README section plus the docstring above both
    # need updating to match.
    if claims.verified and claims.sub:
        return str(claims.sub), "user"

    # Steps 2 and 3 are fabric_mcp_common.trusted_client_ip: it honours the
    # asserted header only from a configured peer, and returns the peer
    # otherwise. Only the `key_type` label is ours, and it comes from this one
    # call so it cannot disagree with the key.
    return (
        trusted_client_ip(
            request,
            trusted_proxies=config.rate_limit_trusted_proxies,
            default=get_remote_address(request),
        ),
        "ip",
    )


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a JSON error response when rate limit is exceeded."""
    key, key_type = _rate_limit_identity(request)
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
            # key_type comes from the same call that produced the key, so the
            # label always describes how the request was actually bucketed.
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

    malformed = invalid_networks(config.rate_limit_trusted_proxies)
    if malformed:
        # Reported once here rather than per request. A typo silently narrowing
        # the trusted set means callers behind the proxy collapse into one
        # bucket, which is a capacity bug that otherwise looks like nothing.
        log.warning(
            "Ignoring malformed RATE_LIMIT_TRUSTED_PROXIES entries: %s",
            ", ".join(malformed),
        )

    if not config.rate_limit_trusted_proxies:
        # Not wrong when the server is exposed directly — the socket peer is the
        # caller. But behind a reverse proxy the peer is the proxy, so every
        # caller lands in one bucket and `rate_limit` becomes a service-wide cap.
        # Silent either way, so say it out loud.
        log.warning(
            "RATE_LIMIT_TRUSTED_PROXIES is empty: rate limiting will key on the "
            "socket peer. Correct if this server is reached directly; if a "
            "reverse proxy fronts it, every caller shares one bucket and %s "
            "becomes a limit for the whole service. Set it to the proxy address.",
            config.rate_limit,
        )

    limiter = Limiter(
        key_func=_rate_limit_key,
        default_limits=[config.rate_limit],
    )
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    log.info("Rate limiting enabled: %s", config.rate_limit)
