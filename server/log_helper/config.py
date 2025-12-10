"""
Logging configuration setup.
"""
from __future__ import annotations

import logging
import sys

from server.config import config
from server.log_helper.formatters import JsonFormatter


def configure_logging() -> None:
    """
    Configure root logger with either text or JSON formatting.

    Sets up a StreamHandler to stdout with the appropriate formatter based on LOG_FORMAT.
    Also configures uvicorn and fastapi loggers to use the same settings.
    """
    root = logging.getLogger()
    root.setLevel(config.log_level)

    # Clean existing handlers (important when reloading to avoid duplicate logs)
    for h in list(root.handlers):
        root.removeHandler(h)

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

    # Align common library loggers with our configuration
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logging.getLogger(name).setLevel(config.log_level)
        logging.getLogger(name).propagate = True
