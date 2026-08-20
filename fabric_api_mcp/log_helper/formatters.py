"""
Custom log formatters for structured logging.

Re-export of ``fabric_mcp_common.logging.JsonFormatter``.
"""
from __future__ import annotations

from fabric_mcp_common.logging import DEFAULT_EXTRA_FIELDS, JsonFormatter

__all__ = ["DEFAULT_EXTRA_FIELDS", "JsonFormatter"]
