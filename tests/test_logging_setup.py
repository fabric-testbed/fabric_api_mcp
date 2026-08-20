"""Logging configuration and the tool decorator binding.

Two regressions are guarded here. Moving code into fabric_mcp_common changed its
logger name, so if configure_logging() stops registering the library namespace,
every library log line becomes unreachable even at LOG_LEVEL=DEBUG. And
tool_logger must keep emitting on ``server.tools``, which existing log queries
and dashboards match on.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from fabric_api_mcp.log_helper import config as lhc
from fabric_api_mcp.log_helper.decorators import tool_logger


class TestAppLoggers:
    def test_declares_this_servers_namespaces(self):
        assert set(lhc.APP_LOGGERS) == {"server", "fabric.mcp"}


class TestConfigureLogging:
    def test_sets_app_loggers_to_the_configured_level(self, monkeypatch, restore_logging):
        monkeypatch.setattr(lhc.config, "log_level", "DEBUG")
        monkeypatch.setattr(lhc.config, "log_format", "text")
        lhc.configure_logging()

        for name in lhc.APP_LOGGERS:
            assert logging.getLogger(name).level == logging.DEBUG, name

    def test_registers_the_library_namespace(self, monkeypatch, restore_logging):
        # The regression this exists for: fabric_mcp_common logs under
        # `fabric.common`, and if that parent is not raised to LOG_LEVEL its
        # DEBUG output is swallowed by the root logger's WARNING.
        monkeypatch.setattr(lhc.config, "log_level", "DEBUG")
        monkeypatch.setattr(lhc.config, "log_format", "text")
        lhc.configure_logging()

        library = logging.getLogger("fabric.common")
        assert library.isEnabledFor(logging.DEBUG), (
            "fabric.common is not at DEBUG — library diagnostics are unreachable"
        )

    def test_root_stays_quiet_so_third_party_noise_is_suppressed(
        self, monkeypatch, restore_logging
    ):
        monkeypatch.setattr(lhc.config, "log_level", "DEBUG")
        monkeypatch.setattr(lhc.config, "log_format", "text")
        lhc.configure_logging()

        assert logging.getLogger().level >= logging.WARNING

    def test_noisy_loggers_are_pinned(self, monkeypatch, restore_logging):
        monkeypatch.setattr(lhc.config, "log_level", "DEBUG")
        monkeypatch.setattr(lhc.config, "log_format", "text")
        lhc.configure_logging()

        assert lhc.NOISY_LOGGERS, "expected a non-empty set of noisy loggers"
        for name in list(lhc.NOISY_LOGGERS)[:3]:
            assert logging.getLogger(name).level >= logging.WARNING, name

    @pytest.mark.parametrize("fmt", ["text", "json"])
    def test_both_formats_configure_cleanly(self, monkeypatch, restore_logging, fmt):
        monkeypatch.setattr(lhc.config, "log_level", "INFO")
        monkeypatch.setattr(lhc.config, "log_format", fmt)
        lhc.configure_logging()  # must not raise
        assert logging.getLogger("server").level == logging.INFO

    def test_emits_a_confirmation_line(self, monkeypatch, restore_logging, capsys):
        monkeypatch.setattr(lhc.config, "log_level", "INFO")
        monkeypatch.setattr(lhc.config, "log_format", "text")
        lhc.configure_logging()

        # Asserted against stderr, not caplog: configure_logging() sets
        # propagate=False on the app loggers to avoid duplicate output, so these
        # records never reach caplog's root handler.
        captured = capsys.readouterr()
        assert "Logging configured" in captured.err
        # stdout must stay clean — stdio transport reserves it for JSON-RPC.
        assert captured.out == ""


class TestToolLogger:
    def test_logs_on_the_server_tools_logger(self, caplog):
        @tool_logger("my_tool")
        async def my_tool():
            return {"ok": True}

        with caplog.at_level(logging.INFO, logger="server.tools"):
            result = asyncio.run(my_tool())

        assert result == {"ok": True}
        names = {r.name for r in caplog.records}
        assert "server.tools" in names, f"expected server.tools, saw {names}"

    def test_preserves_the_wrapped_result(self):
        @tool_logger("passthrough")
        async def passthrough():
            return [1, 2, 3]

        assert asyncio.run(passthrough()) == [1, 2, 3]

    def test_errors_are_logged_and_propagated(self, caplog):
        @tool_logger("failing_tool")
        async def failing_tool():
            raise ValueError("nope")

        with caplog.at_level(logging.ERROR, logger="server.tools"):
            with pytest.raises(ValueError, match="nope"):
                asyncio.run(failing_tool())

        assert any(r.levelno >= logging.ERROR for r in caplog.records)

    def test_credential_bearing_parameters_are_redacted(self, caplog):
        @tool_logger("with_token")
        async def with_token(id_token: str, site: str):
            return site

        with caplog.at_level(logging.DEBUG, logger="server.tools"):
            asyncio.run(with_token(id_token="super-secret-value", site="STAR"))

        blob = " ".join(r.getMessage() for r in caplog.records)
        assert "super-secret-value" not in blob, "token leaked into the logs"
