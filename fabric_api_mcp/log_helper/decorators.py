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
            # Extract request ID from context or tool call parameters for tracing
            ctx = args[0] if args else None
            rid = None
            try:
                if ctx and hasattr(ctx, "request") and ctx.request:
                    rid = ctx.request.headers.get("x-request-id")
            except Exception:
                pass
            rid = rid or uuid.uuid4().hex[:12]

            # Log tool invocation with parameters at DEBUG level
            sanitized_params = _sanitize_params(kwargs)
            log.debug(
                "[%s] invoked with params: %s",
                tool_name,
                sanitized_params,
                extra={"tool": tool_name, "request_id": rid, "params": sanitized_params},
            )

            # Log tool start and measure execution time
            start = time.perf_counter()
            log.info(
                "[%s] >>> START (rid=%s)",
                tool_name,
                rid,
                extra={"tool": tool_name, "request_id": rid},
            )
            try:
                result = await fn(*args, **kwargs)
                dur_ms = round((time.perf_counter() - start) * 1000, 2)

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
                    extra={"tool": tool_name, "request_id": rid, "duration_ms": dur_ms, "result_size": size},
                )
                return result
            except Exception as e:
                # Log errors with timing for debugging
                dur_ms = round((time.perf_counter() - start) * 1000, 2)
                log.exception(
                    "[%s] !!! ERROR after %.2fms: %s (rid=%s)",
                    tool_name,
                    dur_ms,
                    str(e),
                    rid,
                    extra={"tool": tool_name, "request_id": rid, "duration_ms": dur_ms, "error": str(e)},
                )
                raise
        return _async_wrapper
    return _wrap
