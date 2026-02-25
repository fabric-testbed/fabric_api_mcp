"""
Configuration module for FABRIC MCP Server.

Centralizes all environment variable reading and configuration management.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


@dataclass
class ServerConfig:
    """Server configuration loaded from environment variables."""

    # FABRIC service endpoints
    orchestrator_host: str
    credmgr_host: str
    am_host: str
    core_api_host: str

    # Server settings
    port: int
    host: str
    http_debug: bool

    # Logging configuration
    log_level: str
    log_format: Literal["text", "json"]
    uvicorn_access_log: bool

    # Cache settings
    refresh_interval_seconds: int
    cache_max_fetch: int
    max_fetch_for_sort: int

    # Local mode settings
    local_mode: bool
    transport: str
    fabric_rc: str

    @classmethod
    def from_env(cls) -> "ServerConfig":
        """Load configuration from environment variables with sensible defaults."""
        is_local = os.environ.get("FABRIC_LOCAL_MODE", "0") not in ("0", "false", "False", "")
        return cls(
            # FABRIC service endpoints - can be overridden for different deployments
            orchestrator_host=os.environ.get("FABRIC_ORCHESTRATOR_HOST", "orchestrator.fabric-testbed.net"),
            credmgr_host=os.environ.get("FABRIC_CREDMGR_HOST", "cm.fabric-testbed.net"),
            am_host=os.environ.get("FABRIC_AM_HOST", "artifacts.fabric-testbed.net"),
            core_api_host=os.environ.get("FABRIC_CORE_API_HOST", "uis.fabric-testbed.net"),

            # Server settings
            port=int(os.environ.get("PORT", "8000")),
            host=os.environ.get("HOST", "0.0.0.0"),
            http_debug=bool(int(os.environ.get("HTTP_DEBUG", "0"))),

            # Logging configuration
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            log_format=os.environ.get("LOG_FORMAT", "text").lower(),  # "text" | "json"
            uvicorn_access_log=os.environ.get("UVICORN_ACCESS_LOG", "1") not in ("0", "false", "False"),

            # Cache settings
            refresh_interval_seconds=int(os.environ.get("REFRESH_INTERVAL_SECONDS", "300")),  # 5 minutes
            cache_max_fetch=int(os.environ.get("CACHE_MAX_FETCH", "5000")),
            max_fetch_for_sort=int(os.environ.get("MAX_FETCH_FOR_SORT", "5000")),

            # Local mode settings
            local_mode=is_local,
            transport=os.environ.get("FABRIC_MCP_TRANSPORT", "stdio" if is_local else "http"),
            fabric_rc=os.environ.get("FABRIC_RC", os.path.expanduser("~/work/fabric_config/fabric_rc")),
        )

    def print_startup_info(self) -> None:
        """Print configuration on startup for debugging/verification.

        Uses stderr so that stdio transport (which reserves stdout for
        JSON-RPC messages) is not corrupted.
        """
        if self.local_mode:
            return
        import sys
        _p = lambda msg: print(msg, file=sys.stderr)
        _p(f"Local mode: {self.local_mode}")
        _p(f"Transport: {self.transport}")
        if self.local_mode:
            _p(f"Fabric RC: {self.fabric_rc}")
        _p(f"Orchestrator HOST: {self.orchestrator_host}")
        _p(f"Credmgr HOST: {self.credmgr_host}")
        _p(f"Artifact Manager HOST: {self.am_host}")
        _p(f"Core API HOST: {self.core_api_host}")


# Global configuration instance
config = ServerConfig.from_env()
