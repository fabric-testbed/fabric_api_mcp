"""Rate limiting: the key function, the 429 contract, and metric labelling."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest
from fabric_mcp_common.metrics import mcp_rate_limit_hits_total

from fabric_api_mcp.middleware import rate_limit as rl


def make_request(*, client_host="203.0.113.7", headers=None, path="/mcp"):
    """Build a minimal Starlette Request suitable for the key/handler code."""
    from starlette.requests import Request

    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
        "client": (client_host, 54321),
        "server": ("testserver", 80),
    }
    return Request(scope)


#: The handler only reads `.detail`, so a stub avoids depending on slowapi
#: internals that differ across versions.
def exceeded(detail="60 per 1 minute"):
    return SimpleNamespace(detail=detail)


class TestRateLimitKey:
    def test_falls_back_to_client_ip_when_unauthenticated(self, monkeypatch):
        monkeypatch.setattr(rl.config, "rate_limit_trust_proxy_headers", False)
        assert rl._rate_limit_key(make_request(client_host="198.51.100.4")) == "198.51.100.4"

    def test_forwarded_headers_are_ignored_by_default(self, monkeypatch):
        # Security: these headers are client-supplied. If they set the key, a
        # caller could rotate X-Forwarded-For to get a fresh bucket per request
        # and bypass rate limiting entirely.
        monkeypatch.setattr(rl.config, "rate_limit_trust_proxy_headers", False)
        key = rl._rate_limit_key(
            make_request(client_host="10.0.0.1", headers={"x-forwarded-for": "203.0.113.9"})
        )
        assert key == "10.0.0.1", "a spoofable header must not decide the key"

    def test_spoofing_cannot_mint_new_buckets(self, monkeypatch):
        # The bypass, stated directly: many different forged values, one key.
        monkeypatch.setattr(rl.config, "rate_limit_trust_proxy_headers", False)
        keys = {
            rl._rate_limit_key(
                make_request(client_host="10.0.0.1", headers={"x-forwarded-for": forged})
            )
            for forged in ("1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4")
        }
        assert keys == {"10.0.0.1"}

    def test_x_real_ip_is_also_ignored_by_default(self, monkeypatch):
        monkeypatch.setattr(rl.config, "rate_limit_trust_proxy_headers", False)
        key = rl._rate_limit_key(
            make_request(client_host="10.0.0.1", headers={"x-real-ip": "203.0.113.9"})
        )
        assert key == "10.0.0.1"

    def test_forwarded_headers_are_honoured_when_explicitly_trusted(self, monkeypatch):
        # Opt-in for deployments where a reverse proxy overwrites these headers.
        # Without it, every caller behind that proxy shares one bucket.
        monkeypatch.setattr(rl.config, "rate_limit_trust_proxy_headers", True)
        key = rl._rate_limit_key(
            make_request(client_host="10.0.0.1", headers={"x-forwarded-for": "203.0.113.9"})
        )
        assert key == "203.0.113.9"

    def test_leftmost_forwarded_entry_is_used_when_trusted(self, monkeypatch):
        monkeypatch.setattr(rl.config, "rate_limit_trust_proxy_headers", True)
        key = rl._rate_limit_key(
            make_request(
                client_host="10.0.0.1",
                headers={"x-forwarded-for": "203.0.113.9, 70.41.3.18, 150.172.238.178"},
            )
        )
        assert key == "203.0.113.9"


class TestExceededHandler:
    def test_returns_429(self):
        response = rl._rate_limit_exceeded_handler(make_request(), exceeded())
        assert response.status_code == 429

    def test_body_matches_the_documented_error_contract(self):
        response = rl._rate_limit_exceeded_handler(make_request(), exceeded("60 per 1 minute"))
        body = json.loads(response.body)
        # Contract from the server's system prompt: {"error", "details"} with
        # error == "limit_exceeded".
        assert body["error"] == "limit_exceeded"
        assert "60 per 1 minute" in body["details"]
        assert set(body) == {"error", "details"}

    def test_logs_a_warning_with_the_key_and_path(self, caplog):
        with caplog.at_level(logging.WARNING, logger="fabric.mcp"):
            rl._rate_limit_exceeded_handler(make_request(path="/mcp/tools"), exceeded())
        messages = [r.getMessage() for r in caplog.records if r.name == "fabric.mcp"]
        assert any("Rate limit exceeded" in m and "/mcp/tools" in m for m in messages)


class TestMetrics:
    def test_increments_with_ip_key_type_when_unauthenticated(
        self, monkeypatch, counter_value
    ):
        monkeypatch.setattr(rl.config, "metrics_enabled", True)
        before = counter_value(mcp_rate_limit_hits_total, key_type="ip")
        rl._rate_limit_exceeded_handler(make_request(), exceeded())
        after = counter_value(mcp_rate_limit_hits_total, key_type="ip")
        assert after == before + 1

    def test_does_not_record_when_metrics_are_disabled(self, monkeypatch, counter_value):
        monkeypatch.setattr(rl.config, "metrics_enabled", False)
        before = counter_value(mcp_rate_limit_hits_total, key_type="ip")
        rl._rate_limit_exceeded_handler(make_request(), exceeded())
        assert counter_value(mcp_rate_limit_hits_total, key_type="ip") == before

    def test_a_metrics_failure_never_breaks_the_response(self, monkeypatch):
        # The handler swallows metric errors on purpose: a broken counter must
        # not turn a 429 into a 500.
        monkeypatch.setattr(rl.config, "metrics_enabled", True)
        monkeypatch.setattr(
            rl, "request_claims", lambda request: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        response = rl._rate_limit_exceeded_handler(make_request(), exceeded())
        assert response.status_code == 429


class TestRegistration:
    def test_disabled_config_registers_nothing(self, monkeypatch):
        monkeypatch.setattr(rl.config, "rate_limit_enabled", False)
        app = SimpleNamespace(
            state=SimpleNamespace(),
            add_middleware=lambda *a, **k: pytest.fail("middleware added while disabled"),
            add_exception_handler=lambda *a, **k: pytest.fail("handler added while disabled"),
        )
        rl.register_rate_limiter(app)
        assert not hasattr(app.state, "limiter")

    def test_enabled_config_installs_limiter_middleware_and_handler(self, monkeypatch):
        monkeypatch.setattr(rl.config, "rate_limit_enabled", True)
        monkeypatch.setattr(rl.config, "rate_limit", "5/minute")
        added = {"middleware": [], "handlers": []}
        app = SimpleNamespace(
            state=SimpleNamespace(),
            add_middleware=lambda mw, **k: added["middleware"].append(mw),
            add_exception_handler=lambda exc, h: added["handlers"].append((exc, h)),
        )
        rl.register_rate_limiter(app)

        assert app.state.limiter is not None
        assert added["middleware"], "SlowAPIMiddleware was not installed"
        assert added["handlers"], "RateLimitExceeded handler was not installed"
