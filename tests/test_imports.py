"""Import surface.

The server has no unit coverage of its wiring, so an import regression used to
only show up at container start. These tests make that a test failure instead —
including the lazy, inside-a-function imports that a plain module import does
not exercise.
"""
from __future__ import annotations

import importlib

import pytest

#: Every module that survived the fabric_mcp_common extraction.
MODULES = (
    "fabric_api_mcp",
    "fabric_api_mcp.auth",
    "fabric_api_mcp.auth.resolver",
    "fabric_api_mcp.config",
    "fabric_api_mcp.log_helper",
    "fabric_api_mcp.log_helper.config",
    "fabric_api_mcp.log_helper.decorators",
    "fabric_api_mcp.middleware",
    "fabric_api_mcp.middleware.access_log",
    "fabric_api_mcp.middleware.rate_limit",
    "fabric_api_mcp.dependencies.fabric_manager",
    "fabric_api_mcp.tools.projects",
    "fabric_api_mcp.tools.topology",
    "fabric_api_mcp.tools.slices.create",
    "fabric_api_mcp.tools.slices.inspect",
    "fabric_api_mcp.tools.slices.lifecycle",
    "fabric_api_mcp.tools.slices.listing",
    "fabric_api_mcp.tools.slices.modify",
    "fabric_api_mcp.tools.slices.network",
    "fabric_api_mcp.__main__",
)

#: Modules deleted as pure re-exports of fabric_mcp_common. Listed so that
#: reintroducing a shim is a deliberate act rather than an accident.
REMOVED_SHIMS = (
    "fabric_api_mcp.metrics",
    "fabric_api_mcp.auth.token",
    "fabric_api_mcp.log_helper.formatters",
    "fabric_api_mcp.middleware.metrics",
    "fabric_api_mcp.middleware.security_metrics",
)


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    assert importlib.import_module(name) is not None


@pytest.mark.parametrize("name", REMOVED_SHIMS)
def test_removed_shims_stay_removed(name):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(name)


class TestLazyImports:
    """Imports written inside functions, which module import does not reach."""

    def test_main_metrics_middleware(self):
        # fabric_api_mcp/__main__.py, inside the metrics_enabled branch.
        from fabric_mcp_common.metrics import (  # noqa: F401
            MetricsMiddleware,
            SecurityMetricsMiddleware,
            configure,
        )

    def test_rate_limit_counter(self):
        # fabric_api_mcp/middleware/rate_limit.py, inside the exception handler.
        from fabric_mcp_common.metrics import mcp_rate_limit_hits_total

        # The handler labels by key_type; a missing label would raise here.
        mcp_rate_limit_hits_total.labels(key_type="ip")

    def test_fabric_manager_token_file_reader(self):
        # fabric_api_mcp/dependencies/fabric_manager.py, local-mode branch.
        from fabric_mcp_common.auth import read_token_from_file  # noqa: F401


class TestPackageSurface:
    def test_auth_exports_only_the_resolver(self):
        import fabric_api_mcp.auth as auth

        # Token primitives moved to fabric_mcp_common.auth; re-exporting them
        # here again would resurrect the shim this package just shed.
        assert sorted(auth.__all__) == ["optional_token", "require_token", "resolver"]

    def test_version_is_available(self):
        import fabric_api_mcp

        assert fabric_api_mcp.__version__.count(".") == 2
