"""
HTTP metrics middleware for Prometheus instrumentation.

Re-export of ``fabric_mcp_common.metrics.MetricsMiddleware``; the implementation
is shared so all FABRIC MCP servers populate the same metric contract.
"""
from __future__ import annotations

from fabric_mcp_common.metrics import MetricsMiddleware

__all__ = ["MetricsMiddleware"]
