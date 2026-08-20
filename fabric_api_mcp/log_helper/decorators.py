"""
Logging decorators for MCP tools.

The implementation lives in ``fabric_mcp_common.logging``; this module binds it
to this server's configuration once, so the ~25 ``@tool_logger("name")`` call
sites stay unchanged.  Binding here also keeps tool lines on the ``server.tools``
logger, which existing log queries and dashboards match on.
"""
from __future__ import annotations

from fabric_mcp_common.logging import make_tool_logger, sanitize_params
from fabric_mcp_common.logging.decorators import REDACT_PARAMS, SKIP_PARAMS

from fabric_api_mcp.config import config

#: Decorator for async MCP tools: ``@tool_logger("fabric_query_sites")``.
#:
#: ``metrics_enabled`` is a callable so the flag is read at call time rather than
#: at import time, matching the previous behaviour of consulting ``config`` inside
#: the wrapper.
tool_logger = make_tool_logger(
    logger="server.tools",
    metrics_enabled=lambda: config.metrics_enabled,
)

__all__ = ["REDACT_PARAMS", "SKIP_PARAMS", "sanitize_params", "tool_logger"]
