"""Shared fixtures.

Note: these tests import ``fabric_api_mcp``, whose ``__init__`` reads its own
version via ``importlib.metadata``. That fails from a bare source checkout, so
the package must be installed first — ``pip install --no-deps -e .`` is enough.
"""
from __future__ import annotations

import pytest

#: Every environment variable ServerConfig reads. Cleared per test so a value in
#: the developer's shell cannot change what the defaults resolve to.
CONFIG_ENV_VARS = (
    "FABRIC_LOCAL_MODE",
    "FABRIC_ORCHESTRATOR_HOST",
    "FABRIC_CREDMGR_HOST",
    "FABRIC_AM_HOST",
    "FABRIC_CORE_API_HOST",
    "PORT",
    "HOST",
    "HTTP_DEBUG",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "UVICORN_ACCESS_LOG",
    "REFRESH_INTERVAL_SECONDS",
    "CACHE_MAX_FETCH",
    "MAX_FETCH_FOR_SORT",
    "RATE_LIMIT",
    "RATE_LIMIT_ENABLED",
    "RATE_LIMIT_TRUST_PROXY_HEADERS",
    "METRICS_ENABLED",
    "METRICS_CLIENT_IP_LABELS",
    "FABRIC_MCP_TRANSPORT",
    "FABRIC_RC",
    "POST_BOOT_TIMEOUT",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Remove every config environment variable, then hand back monkeypatch."""
    for name in CONFIG_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def counter_value():
    """Read a labelled Prometheus counter, for before/after comparisons.

    Counters are process-global and never reset, so tests must compare deltas
    rather than absolute values.
    """
    def _read(counter, **labels) -> float:
        return counter.labels(**labels)._value.get()

    return _read


@pytest.fixture
def restore_logging():
    """Undo logger level/handler changes made by configure_logging()."""
    import logging

    names = ("", "server", "fabric.mcp", "fabric.common", "server.tools")
    saved = {}
    for name in names:
        lg = logging.getLogger(name)
        saved[name] = (lg.level, list(lg.handlers), lg.propagate)
    yield
    for name, (level, handlers, propagate) in saved.items():
        lg = logging.getLogger(name)
        lg.setLevel(level)
        lg.handlers = handlers
        lg.propagate = propagate
