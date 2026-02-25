"""
HTTP middleware for FABRIC MCP Server.
"""
from fabric_api_mcp.middleware.access_log import access_log_middleware, register_middleware

__all__ = [
    "access_log_middleware",
    "register_middleware",
]
