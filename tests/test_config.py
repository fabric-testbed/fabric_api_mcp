"""ServerConfig environment parsing.

The interesting behaviour is that several defaults *depend on local mode* —
rate limiting, metrics and transport all flip — so local and server deployments
get different safe defaults from the same code.
"""
from __future__ import annotations

import pytest

from fabric_api_mcp.config import ServerConfig

#: Values ServerConfig treats as false. It compares against this exact set, so
#: anything outside it (notably "no", "off", "FALSE") is truthy.
FALSEY = ("0", "false", "False", "")


class TestDefaults:
    def test_server_mode_is_the_default(self, clean_env):
        cfg = ServerConfig.from_env()
        assert cfg.local_mode is False
        assert cfg.transport == "http"

    def test_service_endpoints(self, clean_env):
        cfg = ServerConfig.from_env()
        assert cfg.orchestrator_host == "orchestrator.fabric-testbed.net"
        assert cfg.credmgr_host == "cm.fabric-testbed.net"
        assert cfg.am_host == "artifacts.fabric-testbed.net"
        assert cfg.core_api_host == "uis.fabric-testbed.net"

    def test_server_settings(self, clean_env):
        cfg = ServerConfig.from_env()
        assert cfg.port == 8000
        assert cfg.host == "0.0.0.0"
        assert cfg.http_debug is False

    def test_logging(self, clean_env):
        cfg = ServerConfig.from_env()
        assert cfg.log_level == "INFO"
        assert cfg.log_format == "text"
        assert cfg.uvicorn_access_log is True

    def test_rate_limit(self, clean_env):
        cfg = ServerConfig.from_env()
        assert cfg.rate_limit == "60/minute"


class TestTrustedProxies:
    def test_defaults_cover_loopback_and_private_ranges(self, clean_env):
        # The deployed shape is nginx proxying over a Docker network, so the
        # peer is private. A request off the internet never is.
        proxies = ServerConfig.from_env().rate_limit_trusted_proxies
        assert "127.0.0.0/8" in proxies
        assert "172.16.0.0/12" in proxies
        assert "::1/128" in proxies

    def test_is_a_tuple_so_it_cannot_be_mutated_in_place(self, clean_env):
        assert isinstance(ServerConfig.from_env().rate_limit_trusted_proxies, tuple)

    def test_can_be_narrowed_to_a_specific_proxy(self, clean_env):
        clean_env.setenv("RATE_LIMIT_TRUSTED_PROXIES", "172.18.0.5/32")
        assert ServerConfig.from_env().rate_limit_trusted_proxies == ("172.18.0.5/32",)

    def test_empty_value_trusts_no_proxy(self, clean_env):
        # Correct when the server is exposed directly, with nothing in front.
        clean_env.setenv("RATE_LIMIT_TRUSTED_PROXIES", "")
        assert ServerConfig.from_env().rate_limit_trusted_proxies == ()

    def test_whitespace_and_blank_entries_are_dropped(self, clean_env):
        clean_env.setenv("RATE_LIMIT_TRUSTED_PROXIES", " 10.0.0.0/8 , ,192.168.0.0/16, ")
        assert ServerConfig.from_env().rate_limit_trusted_proxies == (
            "10.0.0.0/8",
            "192.168.0.0/16",
        )


class TestLocalModeFlipsDefaults:
    """Local mode is stdio and single-user, so limits and metrics default off."""

    def test_rate_limiting_off_in_local_mode(self, clean_env):
        clean_env.setenv("FABRIC_LOCAL_MODE", "1")
        assert ServerConfig.from_env().rate_limit_enabled is False

    def test_rate_limiting_on_in_server_mode(self, clean_env):
        assert ServerConfig.from_env().rate_limit_enabled is True

    def test_metrics_off_in_local_mode(self, clean_env):
        clean_env.setenv("FABRIC_LOCAL_MODE", "1")
        assert ServerConfig.from_env().metrics_enabled is False

    def test_metrics_on_in_server_mode(self, clean_env):
        assert ServerConfig.from_env().metrics_enabled is True

    def test_transport_is_stdio_in_local_mode(self, clean_env):
        clean_env.setenv("FABRIC_LOCAL_MODE", "1")
        assert ServerConfig.from_env().transport == "stdio"

    def test_explicit_override_beats_the_local_mode_default(self, clean_env):
        clean_env.setenv("FABRIC_LOCAL_MODE", "1")
        clean_env.setenv("METRICS_ENABLED", "1")
        assert ServerConfig.from_env().metrics_enabled is True


class TestClientIpLabels:
    def test_defaults_on_to_preserve_existing_dashboards(self, clean_env):
        # fabric_mcp_common defaults this OFF (client_ip is unbounded); this
        # server deliberately defaults it ON so its Grafana panels keep working.
        assert ServerConfig.from_env().metrics_client_ip_labels is True

    def test_can_be_disabled_to_bound_cardinality(self, clean_env):
        clean_env.setenv("METRICS_CLIENT_IP_LABELS", "0")
        assert ServerConfig.from_env().metrics_client_ip_labels is False


class TestBooleanParsing:
    @pytest.mark.parametrize("value", FALSEY)
    def test_falsey_values_disable_local_mode(self, clean_env, value):
        clean_env.setenv("FABRIC_LOCAL_MODE", value)
        assert ServerConfig.from_env().local_mode is False

    @pytest.mark.parametrize("value", ["1", "true", "True", "yes"])
    def test_other_values_enable_local_mode(self, clean_env, value):
        clean_env.setenv("FABRIC_LOCAL_MODE", value)
        assert ServerConfig.from_env().local_mode is True

    def test_unrecognised_negatives_are_truthy(self, clean_env):
        # Documents a sharp edge: only the FALSEY set above is false, so "off"
        # and "no" enable local mode rather than disabling it.
        clean_env.setenv("FABRIC_LOCAL_MODE", "off")
        assert ServerConfig.from_env().local_mode is True


class TestNumericAndCaseHandling:
    def test_numeric_fields_are_coerced(self, clean_env):
        clean_env.setenv("PORT", "9001")
        clean_env.setenv("REFRESH_INTERVAL_SECONDS", "42")
        clean_env.setenv("POST_BOOT_TIMEOUT", "7")
        cfg = ServerConfig.from_env()
        assert (cfg.port, cfg.refresh_interval_seconds, cfg.post_boot_timeout) == (9001, 42, 7)

    def test_non_numeric_port_is_a_hard_error(self, clean_env):
        # Better to fail at startup than to bind an unexpected port.
        clean_env.setenv("PORT", "not-a-port")
        with pytest.raises(ValueError):
            ServerConfig.from_env()

    def test_log_level_is_upper_cased(self, clean_env):
        clean_env.setenv("LOG_LEVEL", "debug")
        assert ServerConfig.from_env().log_level == "DEBUG"

    def test_log_format_is_lower_cased(self, clean_env):
        clean_env.setenv("LOG_FORMAT", "JSON")
        assert ServerConfig.from_env().log_format == "json"


class TestStartupBanner:
    def test_local_mode_prints_nothing(self, clean_env, capsys):
        # stdio transport reserves stdout for JSON-RPC, so the banner is
        # suppressed entirely in local mode.
        clean_env.setenv("FABRIC_LOCAL_MODE", "1")
        ServerConfig.from_env().print_startup_info()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_server_mode_prints_to_stderr_only(self, clean_env, capsys):
        ServerConfig.from_env().print_startup_info()
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Orchestrator HOST" in captured.err
