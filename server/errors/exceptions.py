"""
Custom exception hierarchy for FABRIC MCP errors.
"""
from __future__ import annotations

from typing import Dict


class FabricMCPError(Exception):
    """
    Base exception for all FABRIC MCP errors.

    All errors are serialized to JSON format: {"error": "type", "details": "message"}
    """

    def __init__(self, error_type: str, details: str):
        """
        Initialize a FABRIC MCP error.

        Args:
            error_type: The error type identifier (e.g., "unauthorized", "client_error")
            details: Human-readable error message
        """
        self.error_type = error_type
        self.details = details
        super().__init__(details)

    def to_dict(self) -> Dict[str, str]:
        """
        Convert error to dictionary format for JSON responses.

        Returns:
            Dictionary with "error" and "details" keys
        """
        return {"error": self.error_type, "details": self.details}


class AuthenticationError(FabricMCPError):
    """Raised when authentication fails or token is missing."""

    def __init__(self, details: str = "Missing or invalid Authorization Bearer token."):
        """
        Initialize an authentication error.

        Args:
            details: Optional custom error message
        """
        super().__init__("unauthorized", details)


class UpstreamTimeoutError(FabricMCPError):
    """Raised when upstream FABRIC service times out."""

    def __init__(self, details: str):
        """
        Initialize an upstream timeout error.

        Args:
            details: Description of the timeout
        """
        super().__init__("upstream_timeout", details)


class ClientError(FabricMCPError):
    """Raised for client-side errors (invalid input, bad requests)."""

    def __init__(self, details: str):
        """
        Initialize a client error.

        Args:
            details: Description of the client error
        """
        super().__init__("client_error", details)


class ServerError(FabricMCPError):
    """Raised for server-side errors (internal failures)."""

    def __init__(self, details: str):
        """
        Initialize a server error.

        Args:
            details: Description of the server error
        """
        super().__init__("server_error", details)


class LimitExceededError(FabricMCPError):
    """Raised when request exceeds configured limits."""

    def __init__(self, details: str):
        """
        Initialize a limit exceeded error.

        Args:
            details: Description of the limit violation
        """
        super().__init__("limit_exceeded", details)
