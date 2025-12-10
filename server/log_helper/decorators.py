"""
Logging decorators for MCP tools.
"""
from __future__ import annotations

import logging
import time
import uuid
from functools import wraps
from typing import Callable

log = logging.getLogger("fabric.mcp")


def tool_logger(tool_name: str) -> Callable:
    """
    Decorator that wraps MCP tool functions with log_helper and timing.

    Logs tool invocation start/end with request IDs for tracing, execution duration,
    and result size. Helps track performance and debug issues.

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
            rid = rid or kwargs.get("toolCallId") or kwargs.get("tool_call_id") or uuid.uuid4().hex[:12]

            # Log tool start and measure execution time
            start = time.perf_counter()
            log.info("Tool start", extra={"tool": tool_name, "request_id": rid})
            try:
                result = await fn(*args, **kwargs)
                dur_ms = round((time.perf_counter() - start) * 1000, 2)
                # Track result size for performance analysis
                size = None
                if isinstance(result, list):
                    size = len(result)
                elif isinstance(result, dict):
                    size = result.get("count") or len(result)
                log.info("Tool done in %.2fms (size=%s)", dur_ms, size,
                         extra={"tool": tool_name, "request_id": rid, "duration_ms": dur_ms})
                return result
            except Exception:
                # Log errors with timing for debugging
                dur_ms = round((time.perf_counter() - start) * 1000, 2)
                log.exception("Tool error after %.2fms", dur_ms,
                              extra={"tool": tool_name, "request_id": rid, "duration_ms": dur_ms})
                raise
        return _async_wrapper
    return _wrap
