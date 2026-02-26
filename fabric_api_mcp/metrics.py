"""
Prometheus metrics definitions for FABRIC MCP Server.

Central module defining all Prometheus metrics using prometheus-client.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

# HTTP metrics
mcp_http_requests_total = Counter(
    "mcp_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

mcp_http_request_duration_seconds = Histogram(
    "mcp_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=_BUCKETS,
)

mcp_http_requests_in_progress = Gauge(
    "mcp_http_requests_in_progress",
    "Currently active HTTP requests",
    ["method"],
)

# Tool call metrics
mcp_tool_calls_total = Counter(
    "mcp_tool_calls_total",
    "Total tool calls",
    ["tool", "user_sub", "status"],
)

mcp_tool_call_duration_seconds = Histogram(
    "mcp_tool_call_duration_seconds",
    "Tool execution latency in seconds",
    ["tool"],
    buckets=_BUCKETS,
)

# Rate limit metrics
mcp_rate_limit_hits_total = Counter(
    "mcp_rate_limit_hits_total",
    "Total rate limit 429 responses",
    ["key_type"],
)

# Security metrics
mcp_auth_failures_total = Counter(
    "mcp_auth_failures_total",
    "Authentication failures",
    ["reason", "client_ip"],
)

mcp_requests_by_ip_total = Counter(
    "mcp_requests_by_ip_total",
    "Requests by client IP (for geo/anomaly detection)",
    ["client_ip"],
)

mcp_auth_success_total = Counter(
    "mcp_auth_success_total",
    "Successful authentications by user and IP",
    ["user_sub", "client_ip"],
)

# Per-user metrics
mcp_requests_by_user_total = Counter(
    "mcp_requests_by_user_total",
    "Per-user request count",
    ["user_sub"],
)

mcp_requests_by_user_path_total = Counter(
    "mcp_requests_by_user_path_total",
    "Per-user per-path request count",
    ["user_sub", "method", "path"],
)
