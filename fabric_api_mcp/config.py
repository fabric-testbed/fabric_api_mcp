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

    # Rate limiting (server mode)
    rate_limit: str
    rate_limit_enabled: bool
    rate_limit_trusted_proxies: tuple[str, ...]

    # Metrics
    metrics_enabled: bool
    metrics_client_ip_labels: bool

    # Local mode settings
    local_mode: bool
    transport: str
    fabric_rc: str

    # Timeout for post-boot configuration (seconds)
    post_boot_timeout: int

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

            # Rate limiting (server mode)
            rate_limit=os.environ.get("RATE_LIMIT", "60/minute"),
            rate_limit_enabled=os.environ.get("RATE_LIMIT_ENABLED", "0" if is_local else "1")
                               not in ("0", "false", "False", ""),

            # Peers whose X-Real-IP header is trusted for the rate-limit key.
            #
            # Deployed behind nginx (see nginx/default.conf, docker-compose.yml),
            # the socket peer is always the proxy container, so keying on it
            # alone would put every caller in one bucket and cap the whole
            # service at `rate_limit`. Keying on a header instead is only safe
            # when the request demonstrably came from the proxy — which the
            # socket peer proves, and a client cannot forge.
            #
            # Defaults to loopback plus the private ranges Docker networks use,
            # since a request arriving straight off the internet never has a
            # private peer. Set to an empty value to trust no peer (correct if
            # the server is exposed directly), or to specific CIDRs when the
            # proxy sits at a known public address.
            rate_limit_trusted_proxies=tuple(
                entry.strip()
                for entry in os.environ.get(
                    "RATE_LIMIT_TRUSTED_PROXIES",
                    "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7",
                ).split(",")
                if entry.strip()
            ),

            # Metrics
            metrics_enabled=os.environ.get(
                "METRICS_ENABLED", "0" if is_local else "1"
            ) not in ("0", "false", "False", ""),

            # Record real client IPs in `client_ip` metric labels. Defaults on to
            # preserve the existing dashboards; set METRICS_CLIENT_IP_LABELS=0 to
            # bound cardinality (one series per source address otherwise).
            metrics_client_ip_labels=os.environ.get(
                "METRICS_CLIENT_IP_LABELS", "1"
            ) not in ("0", "false", "False", ""),

            # Local mode settings
            local_mode=is_local,
            transport=os.environ.get("FABRIC_MCP_TRANSPORT", "stdio" if is_local else "http"),
            fabric_rc=os.environ.get("FABRIC_RC", os.path.expanduser("~/work/fabric_config/fabric_rc")),

            # Post-boot configuration timeout
            post_boot_timeout=int(os.environ.get("POST_BOOT_TIMEOUT", "600")),
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
        _p(f"Orchestrator HOST: {self.orchestrator_host}")
        _p(f"Credmgr HOST: {self.credmgr_host}")
        _p(f"Artifact Manager HOST: {self.am_host}")
        _p(f"Core API HOST: {self.core_api_host}")


# Global configuration instance
config = ServerConfig.from_env()
