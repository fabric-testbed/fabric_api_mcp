"""
Dependency injection for FabricManager instances.
"""
from __future__ import annotations

import logging
from typing import Tuple

from fabrictestbed.fabric_manager_v2 import FabricManagerV2
from fastmcp.server.dependencies import get_http_headers

from server.auth.token import extract_bearer_token
from server.config import config

log = logging.getLogger("fabric.mcp")


class FabricManagerFactory:
    """Factory for creating FabricManagerV2 instances."""

    def __init__(self, server_config=None):
        """
        Initialize the factory.

        Args:
            server_config: Optional server configuration (defaults to global config)
        """
        self.config = server_config or config

    def create_authenticated(self, token: str) -> Tuple[FabricManagerV2, str]:
        """
        Create a FabricManagerV2 instance with user authentication.

        Args:
            token: Bearer token for authentication

        Returns:
            Tuple of (FabricManagerV2 instance, token string)
        """
        fm = FabricManagerV2(
            credmgr_host=self.config.credmgr_host,
            orchestrator_host=self.config.orchestrator_host,
            core_api_host=self.config.core_api_host,
            http_debug=self.config.http_debug,
            id_token=token
        )
        return fm, token

    def create_for_cache(self) -> FabricManagerV2:
        """
        Create a FabricManagerV2 instance for cache refreshes (no token required).

        Returns:
            FabricManagerV2 instance
        """
        return FabricManagerV2(
            credmgr_host=self.config.credmgr_host,
            orchestrator_host=self.config.orchestrator_host,
            http_debug=self.config.http_debug,
        )


# Global factory instance
fabric_manager_factory = FabricManagerFactory()


def get_fabric_manager() -> Tuple[FabricManagerV2, str]:
    """
    Dependency injection function to create an authenticated FabricManager.

    Extracts the Bearer token from HTTP headers and creates a FabricManagerV2
    instance. This is used for all authenticated tool calls.

    Returns:
        Tuple of (FabricManagerV2 instance, token string)

    Raises:
        ValueError: If Authorization header is missing or invalid
    """
    headers = get_http_headers(include={"authorization"}) or {}
    token = extract_bearer_token(headers)
    if not token:
        log.warning("Missing Authorization header on protected call")
        raise ValueError("Authentication Required: Missing or invalid Authorization Bearer token.")

    return fabric_manager_factory.create_authenticated(token)
