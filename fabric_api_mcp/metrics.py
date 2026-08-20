"""
Prometheus metrics for FABRIC MCP Server.

The metric definitions now live in ``fabric_mcp_common.metrics`` so that every
FABRIC MCP server reports the same names and labels — which is what lets them
share one Grafana dashboard.  This module re-exports them so existing
``from fabric_api_mcp.metrics import ...`` imports keep working.

User identity labels use the FABRIC user UUID (a GUID from the JWT ``uuid``
claim) and email (``email`` claim), not the CILogon ``sub`` URI.
"""
from __future__ import annotations

from fabric_mcp_common.metrics import (
    ALL_METRICS,
    METRIC_NAMES,
    dashboard_path,
    mcp_auth_failures_total,
    mcp_auth_success_total,
    mcp_http_request_duration_seconds,
    mcp_http_requests_in_progress,
    mcp_http_requests_total,
    mcp_rate_limit_hits_total,
    mcp_requests_by_ip_total,
    mcp_requests_by_user_path_total,
    mcp_requests_by_user_total,
    mcp_tool_call_duration_seconds,
    mcp_tool_calls_total,
    record_tool_call,
)

__all__ = [
    "ALL_METRICS",
    "METRIC_NAMES",
    "dashboard_path",
    "mcp_auth_failures_total",
    "mcp_auth_success_total",
    "mcp_http_request_duration_seconds",
    "mcp_http_requests_in_progress",
    "mcp_http_requests_total",
    "mcp_rate_limit_hits_total",
    "mcp_requests_by_ip_total",
    "mcp_requests_by_user_path_total",
    "mcp_requests_by_user_total",
    "mcp_tool_call_duration_seconds",
    "mcp_tool_calls_total",
    "record_tool_call",
]
