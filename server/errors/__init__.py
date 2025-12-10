"""
Error handling for FABRIC MCP Server.
"""
from server.errors.exceptions import (
    AuthenticationError,
    ClientError,
    FabricMCPError,
    LimitExceededError,
    ServerError,
    UpstreamTimeoutError,
)
from server.errors.handlers import register_error_handlers

__all__ = [
    "FabricMCPError",
    "AuthenticationError",
    "UpstreamTimeoutError",
    "ClientError",
    "ServerError",
    "LimitExceededError",
    "register_error_handlers",
]
