"""
Security-focused Prometheus metrics middleware.

Re-export of ``fabric_mcp_common.metrics.SecurityMetricsMiddleware``, which
tracks authentication failures, per-IP request counts, and successful auth by
user+IP for anomaly detection.
"""
from __future__ import annotations

from fabric_mcp_common.metrics import SecurityMetricsMiddleware

__all__ = ["SecurityMetricsMiddleware"]
