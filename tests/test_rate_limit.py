"""Rate limiting: the key function, the 429 contract, and metric labelling."""
from __future__ import annotations

import base64
import json
import logging
from types import SimpleNamespace

import pytest
from fabric_mcp_common.metrics import mcp_rate_limit_hits_total

from fabric_api_mcp.middleware import rate_limit as rl


def forge_jwt(**claims) -> str:
    """Build a JWT with arbitrary claims and a junk signature.

    No signing key is involved — which is the point. Anything that trusts an
    unverified payload decode is trusting this.
    """
    def b64(data: dict) -> str:
        raw = json.dumps(data).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{b64({'alg': 'RS256', 'typ': 'JWT'})}.{b64(claims)}.not-a-real-signature"


def make_request(*, client_host="203.0.113.7", headers=None, path="/mcp", token=None):
    """Build a minimal Starlette Request suitable for the key/handler code."""
    from starlette.requests import Request

    headers = dict(headers or {})
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in headers.items()
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


#: Stands in for the nginx container's address on the Docker network. Matches
#: the default RATE_LIMIT_TRUSTED_PROXIES ranges.
PROXY_PEER = "172.18.0.5"

#: A caller reaching the app directly, off the internet.
DIRECT_PEER = "198.51.100.4"


@pytest.fixture
def trusted_proxies(monkeypatch):
    """Set RATE_LIMIT_TRUSTED_PROXIES for the duration of a test."""
    def _set(*entries):
        monkeypatch.setattr(rl.config, "rate_limit_trusted_proxies", tuple(entries))

    return _set


class TestBehindATrustedProxy:
    """The production shape: nginx proxies /mcp over a Docker network."""

    def test_per_client_buckets_not_one_global_bucket(self, trusted_proxies):
        # The regression this guards: keying on the socket peer alone put every
        # caller behind nginx in a single bucket, capping the whole service at
        # `rate_limit` requests per window.
        trusted_proxies("172.16.0.0/12")
        keys = {
            rl._rate_limit_key(
                make_request(client_host=PROXY_PEER, headers={"x-real-ip": f"203.0.113.{i}"})
            )
            for i in range(1, 6)
        }
        assert len(keys) == 5, "callers behind the proxy must not share one bucket"

    def test_uses_the_address_the_proxy_asserts(self, trusted_proxies):
        trusted_proxies("172.16.0.0/12")
        key = rl._rate_limit_key(
            make_request(client_host=PROXY_PEER, headers={"x-real-ip": "203.0.113.9"})
        )
        assert key == "203.0.113.9"

    def test_x_forwarded_for_is_never_consulted(self, trusted_proxies):
        # nginx sets XFF with $proxy_add_x_forwarded_for, which APPENDS to what
        # the client sent — so its left-most entry is caller-controlled even on
        # a trusted hop. Only X-Real-IP ($remote_addr) overwrites.
        trusted_proxies("172.16.0.0/12")
        key = rl._rate_limit_key(
            make_request(
                client_host=PROXY_PEER,
                headers={"x-forwarded-for": "1.2.3.4, 203.0.113.9"},
            )
        )
        assert key == PROXY_PEER, "X-Forwarded-For must not decide the key"

    def test_client_supplied_xff_cannot_override_the_asserted_address(self, trusted_proxies):
        # The realistic attack behind nginx: the client pre-seeds XFF, nginx
        # appends the true address, so the left-most entry is the forgery.
        trusted_proxies("172.16.0.0/12")
        keys = {
            rl._rate_limit_key(
                make_request(
                    client_host=PROXY_PEER,
                    headers={
                        "x-forwarded-for": f"{forged}, 203.0.113.9",
                        "x-real-ip": "203.0.113.9",
                    },
                )
            )
            for forged in ("1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4")
        }
        assert keys == {"203.0.113.9"}, "forged XFF entries leaked into the key"

    def test_missing_asserted_header_falls_back_to_the_peer(self, trusted_proxies):
        trusted_proxies("172.16.0.0/12")
        key = rl._rate_limit_key(make_request(client_host=PROXY_PEER))
        assert key == PROXY_PEER


class TestDirectlyExposed:
    """No trusted proxy in front: headers must carry no weight at all."""

    def test_untrusted_peer_headers_are_ignored(self, trusted_proxies):
        trusted_proxies("172.16.0.0/12")
        key = rl._rate_limit_key(
            make_request(client_host=DIRECT_PEER, headers={"x-real-ip": "10.9.9.9"})
        )
        assert key == DIRECT_PEER

    def test_spoofing_cannot_mint_new_buckets(self, trusted_proxies):
        trusted_proxies("172.16.0.0/12")
        keys = {
            rl._rate_limit_key(
                make_request(client_host=DIRECT_PEER, headers={"x-real-ip": forged})
            )
            for forged in ("1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4")
        }
        assert keys == {DIRECT_PEER}

    def test_empty_trusted_list_trusts_nothing(self, trusted_proxies):
        trusted_proxies()
        key = rl._rate_limit_key(
            make_request(client_host=PROXY_PEER, headers={"x-real-ip": "203.0.113.9"})
        )
        assert key == PROXY_PEER


class TestTrustedProxyMatching:
    def test_nothing_is_trusted_by_default(self):
        # The default must not guess at the network. Trusting a whole private
        # range would cover every other container, VPN client and LAN host that
        # can reach this port — each able to forge X-Real-IP and mint buckets.
        for host in ("127.0.0.1", "::1", "172.18.0.5", "10.1.2.3", "192.168.1.10"):
            assert not rl._is_trusted_proxy(host), f"{host} trusted by default"

    def test_an_exact_proxy_address_matches(self, trusted_proxies):
        trusted_proxies("172.31.240.10/32")
        assert rl._is_trusted_proxy("172.31.240.10")

    def test_neighbours_of_an_exact_proxy_address_do_not_match(self, trusted_proxies):
        # A /32 is the point: the container next door on the same network is not
        # the proxy and must not be able to assert a client address.
        trusted_proxies("172.31.240.10/32")
        for host in ("172.31.240.11", "172.31.240.9", "172.31.240.1"):
            assert not rl._is_trusted_proxy(host), host

    def test_public_addresses_are_not_trusted(self, trusted_proxies):
        trusted_proxies("172.16.0.0/12")
        for host in ("203.0.113.9", "8.8.8.8", "198.51.100.4"):
            assert not rl._is_trusted_proxy(host), host

    def test_missing_or_unparseable_peer_is_not_trusted(self, trusted_proxies):
        trusted_proxies("172.16.0.0/12")
        for host in (None, "", "not-an-ip", "unix-socket"):
            assert not rl._is_trusted_proxy(host)

    def test_malformed_config_entries_are_skipped_not_fatal(self, trusted_proxies, caplog):
        trusted_proxies("not-a-cidr", "172.16.0.0/12")
        with caplog.at_level(logging.WARNING, logger="fabric.mcp"):
            assert rl._is_trusted_proxy(PROXY_PEER) is True
        assert any("malformed" in r.getMessage().lower() for r in caplog.records)

    def test_ipv6_proxies_can_be_declared(self, trusted_proxies):
        trusted_proxies("::1/128")
        assert rl._is_trusted_proxy("::1")
        assert not rl._is_trusted_proxy("::2")


class TestVerifiedSubject:
    def test_forged_jwt_subject_cannot_decide_the_key(self, trusted_proxies):
        # A JWT payload can be base64-encoded by hand with no signing key, so an
        # unverified `sub` is attacker-controlled. It must not set the bucket.
        trusted_proxies("172.16.0.0/12")
        key = rl._rate_limit_key(
            make_request(client_host=DIRECT_PEER, token=forge_jwt(sub="victim-or-whoever"))
        )
        assert key == DIRECT_PEER, "an unverified JWT sub must not decide the key"

    def test_rotating_forged_subjects_cannot_mint_new_buckets(self, trusted_proxies):
        trusted_proxies("172.16.0.0/12")
        keys = {
            rl._rate_limit_key(
                make_request(client_host=DIRECT_PEER, token=forge_jwt(sub=f"attacker-{i}"))
            )
            for i in range(6)
        }
        assert keys == {DIRECT_PEER}

    def test_no_real_request_can_produce_verified_claims(self, trusted_proxies):
        # Documents why step 1 of the key ordering never fires: this server has
        # no verifier wired, and request_claims() takes none, so its claims are
        # always verified=False. Keeps the README honest — per-user keying is
        # not a configuration switch. If this ever fails, verification was
        # added and the docs need updating with it.
        from fabric_mcp_common.integrations.starlette import request_claims

        trusted_proxies("172.16.0.0/12")
        claims = request_claims(make_request(token=forge_jwt(sub="someone")))
        assert claims.sub == "someone"
        assert claims.verified is False

    def test_verified_claims_come_only_from_the_request_state_slot(self):
        # The documented enabling mechanism: request_claims() returns whatever
        # TokenClaims a middleware left on request.state, so that is where a
        # verifier would publish. Asserted so the README instruction cannot rot.
        from fabric_mcp_common.auth import TokenClaims
        from fabric_mcp_common.integrations.starlette import (
            CLAIMS_STATE_ATTR,
            request_claims,
        )

        request = make_request(token=forge_jwt(sub="unverified-value"))
        setattr(
            request.state,
            CLAIMS_STATE_ATTR,
            TokenClaims({"sub": "verified-value"}, verified=True),
        )

        claims = request_claims(request)
        assert claims.verified is True
        assert claims.sub == "verified-value"
        assert rl._rate_limit_key(request) == "verified-value"

    def test_a_verified_subject_is_used_when_available(self, monkeypatch):
        verified = SimpleNamespace(verified=True, sub="real-user-uuid")
        monkeypatch.setattr(rl, "request_claims", lambda request: verified)
        assert rl._rate_limit_key(make_request(client_host=DIRECT_PEER)) == "real-user-uuid"

    def test_a_verified_subject_beats_a_proxy_asserted_address(
        self, monkeypatch, trusted_proxies
    ):
        # Proven identity is more specific than an address.
        trusted_proxies("172.16.0.0/12")
        verified = SimpleNamespace(verified=True, sub="real-user-uuid")
        monkeypatch.setattr(rl, "request_claims", lambda request: verified)
        key = rl._rate_limit_key(
            make_request(client_host=PROXY_PEER, headers={"x-real-ip": "203.0.113.9"})
        )
        assert key == "real-user-uuid"

    def test_verified_claims_without_a_subject_fall_back_to_address(self, monkeypatch):
        verified_no_sub = SimpleNamespace(verified=True, sub=None)
        monkeypatch.setattr(rl, "request_claims", lambda request: verified_no_sub)
        assert rl._rate_limit_key(make_request(client_host=DIRECT_PEER)) == DIRECT_PEER


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

    def test_a_forged_token_cannot_relabel_the_hit_as_user(
        self, monkeypatch, trusted_proxies, counter_value
    ):
        # The label must describe how the request was really bucketed. Deriving
        # it from `sub` presence let any caller flip it to "user" by sending a
        # forged token, while the bucket was actually the address.
        monkeypatch.setattr(rl.config, "metrics_enabled", True)
        trusted_proxies("172.16.0.0/12")

        before_user = counter_value(mcp_rate_limit_hits_total, key_type="user")
        before_ip = counter_value(mcp_rate_limit_hits_total, key_type="ip")

        rl._rate_limit_exceeded_handler(
            make_request(client_host=DIRECT_PEER, token=forge_jwt(sub="pretend-user")),
            exceeded(),
        )

        assert counter_value(mcp_rate_limit_hits_total, key_type="user") == before_user
        assert counter_value(mcp_rate_limit_hits_total, key_type="ip") == before_ip + 1

    def test_label_says_user_only_for_a_verified_subject(
        self, monkeypatch, counter_value
    ):
        monkeypatch.setattr(rl.config, "metrics_enabled", True)
        verified = SimpleNamespace(verified=True, sub="real-user-uuid")
        monkeypatch.setattr(rl, "request_claims", lambda request: verified)

        before = counter_value(mcp_rate_limit_hits_total, key_type="user")
        rl._rate_limit_exceeded_handler(make_request(), exceeded())
        assert counter_value(mcp_rate_limit_hits_total, key_type="user") == before + 1

    def test_logged_key_matches_the_labelled_kind(self, monkeypatch, trusted_proxies, caplog):
        # The warning and the metric come from one call, so they cannot diverge.
        trusted_proxies("172.16.0.0/12")
        monkeypatch.setattr(rl.config, "metrics_enabled", False)
        with caplog.at_level(logging.WARNING, logger="fabric.mcp"):
            rl._rate_limit_exceeded_handler(
                make_request(client_host=PROXY_PEER, headers={"x-real-ip": "203.0.113.9"}),
                exceeded(),
            )
        assert any("key=203.0.113.9" in r.getMessage() for r in caplog.records)

    def test_does_not_record_when_metrics_are_disabled(self, monkeypatch, counter_value):
        monkeypatch.setattr(rl.config, "metrics_enabled", False)
        before = counter_value(mcp_rate_limit_hits_total, key_type="ip")
        rl._rate_limit_exceeded_handler(make_request(), exceeded())
        assert counter_value(mcp_rate_limit_hits_total, key_type="ip") == before

    def test_a_metrics_failure_never_breaks_the_response(self, monkeypatch):
        # The handler swallows metric errors on purpose: a broken counter must
        # not turn a 429 into a 500. Patch the counter itself rather than
        # request_claims — the latter is also used for key derivation, outside
        # the metrics try/except, so breaking it would test the wrong thing.
        import fabric_mcp_common.metrics as metrics_mod

        class Exploding:
            def labels(self, **_kwargs):
                raise RuntimeError("counter is broken")

        monkeypatch.setattr(rl.config, "metrics_enabled", True)
        monkeypatch.setattr(metrics_mod, "mcp_rate_limit_hits_total", Exploding())

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

    def test_warns_when_no_trusted_proxy_is_declared(self, monkeypatch, caplog):
        # Silent either way, so it must be said: behind a proxy this collapses
        # every caller into one bucket.
        monkeypatch.setattr(rl.config, "rate_limit_enabled", True)
        monkeypatch.setattr(rl.config, "rate_limit_trusted_proxies", ())
        app = SimpleNamespace(
            state=SimpleNamespace(),
            add_middleware=lambda *a, **k: None,
            add_exception_handler=lambda *a, **k: None,
        )
        with caplog.at_level(logging.WARNING, logger="fabric.mcp"):
            rl.register_rate_limiter(app)
        assert any(
            "RATE_LIMIT_TRUSTED_PROXIES is empty" in r.getMessage()
            for r in caplog.records
        )

    def test_no_warning_when_a_proxy_is_declared(self, monkeypatch, caplog):
        monkeypatch.setattr(rl.config, "rate_limit_enabled", True)
        monkeypatch.setattr(rl.config, "rate_limit_trusted_proxies", ("172.31.240.10/32",))
        app = SimpleNamespace(
            state=SimpleNamespace(),
            add_middleware=lambda *a, **k: None,
            add_exception_handler=lambda *a, **k: None,
        )
        with caplog.at_level(logging.WARNING, logger="fabric.mcp"):
            rl.register_rate_limiter(app)
        assert not any(
            "RATE_LIMIT_TRUSTED_PROXIES is empty" in r.getMessage()
            for r in caplog.records
        )

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
