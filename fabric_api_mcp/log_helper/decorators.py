"""
Logging decorators for MCP tools.
"""
from __future__ import annotations

import logging
import time
import uuid
from functools import wraps
from typing import Any, Callable, Dict

log = logging.getLogger("server.tools")

# Parameters to redact from logs (security)
REDACT_PARAMS = frozenset({"token", "password", "secret", "key", "credential", "auth"})

# Parameters to skip in logs (too verbose or not useful)
SKIP_PARAMS: frozenset = frozenset()


def _sanitize_params(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize parameters for logging: redact secrets, skip noise.
    """
    sanitized = {}
    for k, v in kwargs.items():
        if k in SKIP_PARAMS:
            continue
        # Redact sensitive parameters
        if any(secret in k.lower() for secret in REDACT_PARAMS):
            sanitized[k] = "***REDACTED***"
        # Truncate very long strings
        elif isinstance(v, str) and len(v) > 200:
            sanitized[k] = f"{v[:200]}... ({len(v)} chars)"
        else:
            sanitized[k] = v
    return sanitized


def tool_logger(tool_name: str) -> Callable:
    """
    Decorator that wraps MCP tool functions with logging and timing.

    Logs:
    - Tool invocation with input parameters (DEBUG)
    - Tool start (INFO)
    - Tool completion with duration and result size (INFO)
    - Tool errors with stack trace (ERROR)

    Args:
        tool_name: Name of the tool being wrapped (for log messages)

    Returns:
        Decorator function that wraps async tool functions
    """
    def _wrap(fn):
        @wraps(fn)  # preserves __name__, __doc__, annotations for FastMCP
        async def _async_wrapper(*args, **kwargs):
            # Extract request ID and user identity from HTTP headers for tracing
            ctx = args[0] if args else None
            rid = None
            user_sub = ""
            user_email = ""
            client_ip = ""
            try:
                from fastmcp.server.dependencies import get_http_headers
                headers = get_http_headers(include={"authorization", "x-request-id",
                                                     "x-real-ip", "x-forwarded-for"}) or {}
                rid = headers.get("x-request-id")

                # Extract user identity from JWT
                from fabric_api_mcp.auth.token import decode_token_claims, extract_bearer_token
                token = extract_bearer_token(headers)
                if token:
                    claims = decode_token_claims(token)
                    user_sub = claims.get("sub", "")
                    user_email = claims.get("email", "")

                # Extract client IP
                client_ip = headers.get("x-real-ip", "")
                if not client_ip:
                    forwarded = headers.get("x-forwarded-for", "")
                    if forwarded:
                        client_ip = forwarded.split(",")[0].strip()
            except Exception:
                pass
            rid = rid or uuid.uuid4().hex[:12]
            user_display = user_email or user_sub or ""

            # Common extra fields for all log entries
            extra_base = {
                "tool": tool_name,
                "request_id": rid,
                "user_sub": user_sub,
                "user_email": user_email,
                "client_ip": client_ip,
            }

            # Log tool invocation with parameters at DEBUG level
            sanitized_params = _sanitize_params(kwargs)
            log.debug(
                "[%s] invoked with params: %s",
                tool_name,
                sanitized_params,
                extra={**extra_base, "params": sanitized_params},
            )

            # Log tool start and measure execution time
            start = time.perf_counter()
            if user_display:
                log.info(
                    "[%s] >>> START (rid=%s, user=%s, ip=%s)",
                    tool_name,
                    rid,
                    user_display,
                    client_ip,
                    extra=extra_base,
                )
            else:
                log.info(
                    "[%s] >>> START (rid=%s)",
                    tool_name,
                    rid,
                    extra=extra_base,
                )
            try:
                result = await fn(*args, **kwargs)
                dur_ms = round((time.perf_counter() - start) * 1000, 2)
                dur_s = dur_ms / 1000

                # Record Prometheus tool metrics (server mode only)
                try:
                    from fabric_api_mcp.config import config as _cfg
                    if _cfg.metrics_enabled:
                        from fabric_api_mcp.metrics import (
                            mcp_tool_calls_total,
                            mcp_tool_call_duration_seconds,
                        )
                        mcp_tool_calls_total.labels(
                            tool=tool_name, user_sub=user_sub, status="ok",
                        ).inc()
                        mcp_tool_call_duration_seconds.labels(tool=tool_name).observe(dur_s)
                except Exception:
                    pass

                # Track result size for performance analysis
                size = None
                if isinstance(result, list):
                    size = len(result)
                elif isinstance(result, dict):
                    size = result.get("count") or len(result)

                log.info(
                    "[%s] <<< DONE in %.2fms (result_size=%s, rid=%s)",
                    tool_name,
                    dur_ms,
                    size,
                    rid,
                    extra={**extra_base, "duration_ms": dur_ms, "result_size": size},
                )
                return result
            except Exception as e:
                # Log errors with timing for debugging
                dur_ms = round((time.perf_counter() - start) * 1000, 2)
                dur_s = dur_ms / 1000

                # Record Prometheus tool error metrics (server mode only)
                try:
                    from fabric_api_mcp.config import config as _cfg
                    if _cfg.metrics_enabled:
                        from fabric_api_mcp.metrics import (
                            mcp_tool_calls_total,
                            mcp_tool_call_duration_seconds,
                        )
                        mcp_tool_calls_total.labels(
                            tool=tool_name, user_sub=user_sub, status="error",
                        ).inc()
                        mcp_tool_call_duration_seconds.labels(tool=tool_name).observe(dur_s)
                except Exception:
                    pass

                log.exception(
                    "[%s] !!! ERROR after %.2fms: %s (rid=%s)",
                    tool_name,
                    dur_ms,
                    str(e),
                    rid,
                    extra={**extra_base, "duration_ms": dur_ms, "error": str(e)},
                )
                raise
        return _async_wrapper
    return _wrap
