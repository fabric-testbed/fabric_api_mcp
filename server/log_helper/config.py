"""
Logging configuration setup.
"""
from __future__ import annotations

import logging
import sys

from server.config import config
from server.log_helper.formatters import JsonFormatter

# Noisy third-party loggers to silence (set to WARNING or higher)
NOISY_LOGGERS = (
    # HTTP clients
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "aiohttp",
    # Docker/container
    "docker",
    "dockerpty",
    "container",
    # Redis/cache
    "redis",
    "aioredis",
    "hiredis",
    # Database
    "sqlalchemy",
    "alembic",
    "asyncpg",
    "psycopg2",
    # Async/event loop
    "asyncio",
    "concurrent",
    # Cryptography/auth
    "paramiko",
    "cryptography",
    "jwt",
    "oauthlib",
    # Other common noisy libs
    "botocore",
    "boto3",
    "s3transfer",
    "kubernetes",
    "google",
    "azure",
    "watchfiles",
    "watchdog",
    "filelock",
    "charset_normalizer",
    "multipart",
    "anyio",
    "starlette",
    # Fabric SDK internals (if too verbose)
    "fabric_cf",
    "fim",
)


def configure_logging() -> None:
    """
    Configure logging with selective verbosity.

    - Root logger: WARNING (to quiet third-party noise)
    - 'server' logger: User-configured level (LOG_LEVEL env var)
    - 'fabric.mcp' logger: User-configured level
    - Noisy third-party loggers: WARNING (unless user sets LOG_LEVEL higher)

    This allows DEBUG logging for fabric_mcp code without flooding logs
    with debug output from docker, redis, httpx, etc.
    """
    user_level = getattr(logging, config.log_level, logging.INFO)

    # Root logger at WARNING to suppress third-party debug noise
    root = logging.getLogger()
    root_level = max(user_level, logging.WARNING)  # At least WARNING for root
    root.setLevel(root_level)

    # Clean existing handlers (important when reloading to avoid duplicate logs)
    for h in list(root.handlers):
        root.removeHandler(h)

    # Create handler with formatter
    handler = logging.StreamHandler(sys.stdout)
    if config.log_format == "json":
        fmt = JsonFormatter()
    else:
        fmt = logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    handler.setFormatter(fmt)
    root.addHandler(handler)

    # Enable user-configured level for our application loggers
    app_loggers = (
        "server",           # All server.* modules (server.utils, server.tools, etc.)
        "fabric.mcp",       # Main MCP logger
    )
    for name in app_loggers:
        logger = logging.getLogger(name)
        logger.setLevel(user_level)
        logger.propagate = True

    # Silence noisy third-party loggers
    noise_level = max(user_level, logging.WARNING)
    for name in NOISY_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(noise_level)

    # Framework loggers: follow user level but not below INFO
    framework_level = max(user_level, logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "fastmcp"):
        logger = logging.getLogger(name)
        logger.setLevel(framework_level)
        logger.propagate = True

    # Log the logging configuration itself (at INFO so it's visible)
    setup_logger = logging.getLogger("server.log_helper.config")
    setup_logger.info(
        "Logging configured: app_level=%s, root_level=%s, framework_level=%s",
        logging.getLevelName(user_level),
        logging.getLevelName(root_level),
        logging.getLevelName(framework_level),
    )
