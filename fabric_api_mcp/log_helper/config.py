"""
Logging configuration setup.

Delegates to ``fabric_mcp_common.logging.configure_logging``, passing this
server's own logger names.  The library's namespace (``fabric.common``) is
registered automatically, so library diagnostics honour ``LOG_LEVEL`` instead of
being clamped by the root logger.
"""
from __future__ import annotations

import logging

from fabric_mcp_common.logging import (
    FRAMEWORK_LOGGERS,
    NOISY_LOGGERS,
    configure_logging as _configure_logging,
    describe_configuration,
)

from fabric_api_mcp.config import config

#: This server's own logger names, set to LOG_LEVEL.
APP_LOGGERS = (
    "server",       # All server.* modules (server.utils, server.tools, etc.)
    "fabric.mcp",   # Main MCP logger
)

# Kept as module attributes for backward compatibility with anything that
# imported them from here.
__all__ = [
    "APP_LOGGERS",
    "FRAMEWORK_LOGGERS",
    "NOISY_LOGGERS",
    "configure_logging",
]


def configure_logging() -> None:
    """
    Configure logging with selective verbosity.

    - Root logger: WARNING (to quiet third-party noise)
    - 'server' logger: User-configured level (LOG_LEVEL env var)
    - 'fabric.mcp' logger: User-configured level
    - 'fabric.common' logger: User-configured level (shared library)
    - Noisy third-party loggers: WARNING (unless user sets LOG_LEVEL higher)

    This allows DEBUG logging for fabric_mcp code without flooding logs
    with debug output from docker, redis, httpx, etc.
    """
    _configure_logging(
        level=config.log_level,
        fmt=config.log_format,
        app_loggers=APP_LOGGERS,
    )

    setup_logger = logging.getLogger("server.log_helper.config")
    setup_logger.info("Logging configured: %s", describe_configuration(config.log_level))
