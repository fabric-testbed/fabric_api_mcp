"""The shared token resolver.

The property that matters most here is that a local token file is never used to
serve someone else's request in server mode, and conversely that a request
header cannot be used in local mode. Both are decided by how the resolver is
built, so that construction is asserted directly.
"""
from __future__ import annotations

import importlib
import logging

import pytest
from fabric_mcp_common.auth import MissingTokenError

from fabric_api_mcp.auth.resolver import optional_token, require_token, resolver

# Note: `from fabric_api_mcp.auth import resolver` yields the TokenResolver
# *object*, because auth/__init__.py re-exports it under the same name as the
# submodule. Import the module explicitly to avoid that shadowing.
resolver_module = importlib.import_module("fabric_api_mcp.auth.resolver")

# The resolver is a module-level singleton built from config at import time, so
# its mode cannot be changed per test. Assertions about "no token available"
# only hold in server mode; skip them if the suite runs with local mode on.
from fabric_api_mcp.config import config  # noqa: E402

server_mode_only = pytest.mark.skipif(
    config.local_mode,
    reason="resolver reads a token file in local mode; these assert header-only behaviour",
)


class TestResolverConstruction:
    def test_header_is_never_trusted_in_local_mode(self):
        # build_resolver(..., allow_header_in_local_mode=False). If this ever
        # flips, a local-mode server would accept a caller-supplied token.
        import inspect

        source = inspect.getsource(resolver_module)
        assert "allow_header_in_local_mode=False" in source

    def test_a_single_shared_resolver_is_exposed(self):
        assert resolver is resolver_module.resolver


class TestRequireToken:
    @server_mode_only
    def test_raises_when_no_token_is_available(self):
        # No request context and no token file: nothing can identify the caller.
        with pytest.raises(MissingTokenError):
            require_token()

    def test_missing_token_error_is_a_valueerror(self):
        # Existing handlers catch ValueError and build {"error","details"}
        # payloads from it; breaking this changes the wire contract.
        assert issubclass(MissingTokenError, ValueError)

    @server_mode_only
    def test_logs_the_original_wording_for_alerting(self, caplog):
        # Log-based alerting matches this exact line on the fabric.mcp logger.
        with caplog.at_level(logging.WARNING, logger="fabric.mcp"):
            with pytest.raises(MissingTokenError):
                require_token()

        records = [r for r in caplog.records if r.name == "fabric.mcp"]
        assert records, "expected a warning on the fabric.mcp logger"
        assert any(
            r.getMessage() == "Missing Authorization header on protected call"
            for r in records
        )


class TestOptionalToken:
    def test_returns_none_outside_a_request(self):
        # Tools call this unconditionally; outside a request it must be None
        # rather than raising, so unauthenticated reads still work.
        assert optional_token() is None

    def test_does_not_fall_back_to_a_token_file(self, tmp_path, monkeypatch):
        # Header-only by design. A token file on disk must not leak into a
        # request that did not present one.
        token_file = tmp_path / "token.json"
        token_file.write_text('{"id_token": "should-not-be-read"}')
        monkeypatch.setenv("FABRIC_TOKEN_LOCATION", str(token_file))

        assert optional_token() is None


class TestExportedSurface:
    def test_all_lists_exactly_the_public_helpers(self):
        assert sorted(resolver_module.__all__) == [
            "optional_token",
            "require_token",
            "resolver",
        ]
