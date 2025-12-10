"""
Custom log_helper formatters for structured log_helper.
"""
from __future__ import annotations

import json
import logging


class JsonFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured log_helper.

    Outputs log records as JSON objects with standard fields (timestamp, level, logger, message)
    plus any extra context fields like request_id, tool name, duration, etc.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record as JSON.

        Args:
            record: The log record to format

        Returns:
            JSON-formatted log string
        """
        base = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Include extra fields if present (for request tracing and performance metrics)
        for k in ("request_id", "tool", "path", "method", "status", "duration_ms", "client"):
            if hasattr(record, k):
                base[k] = getattr(record, k)
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False)
