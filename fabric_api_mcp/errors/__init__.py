"""
Error handling for FABRIC MCP Server.
"""
from fabric_api_mcp.errors.exceptions import (
    AuthenticationError,
    ClientError,
    FabricMCPError,
    LimitExceededError,
    ServerError,
    UpstreamTimeoutError,
)
from fabric_api_mcp.errors.handlers import register_error_handlers

__all__ = [
    "FabricMCPError",
    "AuthenticationError",
    "UpstreamTimeoutError",
    "ClientError",
    "ServerError",
    "LimitExceededError",
    "register_error_handlers",
]
