"""
Security-focused Prometheus metrics middleware.

Tracks authentication failures, per-IP request counts,
and successful auth by user+IP for anomaly detection.
"""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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


class SecurityMetricsMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that records security-related Prometheus metrics."""

    async def dispatch(self, request: Request, call_next) -> Response:
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
            mcp_auth_failures_total.labels(reason="malformed_header", client_ip=client_ip).inc()
        elif not token and path.startswith("/mcp"):
            mcp_auth_failures_total.labels(reason="missing_token", client_ip=client_ip).inc()
        elif token:
            claims = decode_token_claims(token)
            if not claims:
                mcp_auth_failures_total.labels(reason="invalid_jwt", client_ip=client_ip).inc()
            else:
                _check_expiry(token, claims, client_ip)
                user_uuid = claims.get("uuid", "")
                user_email = claims.get("email", "unknown")
                mcp_auth_success_total.labels(
                    user_uuid=user_uuid, user_email=user_email, client_ip=client_ip,
                ).inc()

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
