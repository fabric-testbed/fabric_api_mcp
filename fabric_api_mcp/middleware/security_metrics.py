"""
Security-focused Prometheus metrics middleware.

Tracks authentication failures, per-IP request counts,
and successful auth by user+IP for anomaly detection.
"""
from __future__ import annotations

import time

from fastapi import Request
from fastmcp import FastMCP

from fabric_api_mcp.auth.token import decode_token_claims, extract_bearer_token
from fabric_api_mcp.metrics import (
    mcp_auth_failures_total,
    mcp_auth_success_total,
    mcp_requests_by_ip_total,
)


def _get_client_ip(request: Request) -> str:
    """Extract client IP from X-Real-IP, X-Forwarded-For, or request.client."""
    ip = request.headers.get("x-real-ip")
    if ip:
        return ip
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def security_metrics_middleware(request: Request, call_next):
    """
    Middleware that records security-related Prometheus metrics.

    Tracks:
    - Every request by client IP (for spotting unusual IPs)
    - Auth failures: missing token, malformed token, expired/invalid JWT
    - Successful auth: user_sub + client IP pairs (for spotting account sharing
      or compromised tokens used from unexpected IPs)
    """
    path = request.url.path

    # Skip metrics endpoint
    if path == "/metrics":
        return await call_next(request)

    client_ip = _get_client_ip(request)

    # Track every request by IP
    mcp_requests_by_ip_total.labels(client_ip=client_ip).inc()

    # Inspect auth header
    headers = dict(request.headers)
    auth_header = headers.get("authorization", "").strip()
    token = extract_bearer_token(headers)

    if auth_header and not token:
        # Had an Authorization header but it wasn't a valid Bearer format
        mcp_auth_failures_total.labels(reason="malformed_header", client_ip=client_ip).inc()
    elif not token and path.startswith("/mcp"):
        # No token at all on an MCP endpoint (requires auth)
        mcp_auth_failures_total.labels(reason="missing_token", client_ip=client_ip).inc()
    elif token:
        claims = decode_token_claims(token)
        if not claims:
            # Token present but couldn't decode (not a valid JWT)
            mcp_auth_failures_total.labels(reason="invalid_jwt", client_ip=client_ip).inc()
        else:
            # Check for expiration
            _check_expiry(token, claims, client_ip)

            user_sub = claims.get("sub", "unknown")
            mcp_auth_success_total.labels(user_sub=user_sub, client_ip=client_ip).inc()

    response = await call_next(request)
    return response


def _check_expiry(token: str, claims: dict, client_ip: str) -> None:
    """Check JWT expiration from the raw payload (best-effort)."""
    try:
        import base64
        import json

        parts = token.split(".")
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        exp = payload.get("exp")
        if exp is not None and exp < time.time():
            mcp_auth_failures_total.labels(reason="expired_token", client_ip=client_ip).inc()
    except Exception:
        pass


def register_security_metrics_middleware(mcp: FastMCP) -> None:
    """Register the security metrics middleware with the FastMCP application."""
    if hasattr(mcp, "app") and mcp.app:
        mcp.app.middleware("http")(security_metrics_middleware)
