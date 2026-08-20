"""docker-compose.yml must agree with itself about which peer is the proxy.

The rate-limit key trusts `X-Real-IP` only from `RATE_LIMIT_TRUSTED_PROXIES`.
That value and the nginx container's pinned address are two halves of one
decision written in two places, so they can drift — and drift is silent: too
narrow and every caller shares one bucket, too wide and any host in range can
forge the header. These tests pin them together.
"""
from __future__ import annotations

import ipaddress
import pathlib

import pytest

yaml = pytest.importorskip("yaml")

COMPOSE = pathlib.Path(__file__).resolve().parent.parent / "docker-compose.yml"

pytestmark = pytest.mark.skipif(
    not COMPOSE.is_file(), reason="docker-compose.yml not present"
)


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text())


@pytest.fixture(scope="module")
def trusted(compose):
    raw = compose["services"]["mcp-server"]["environment"]["RATE_LIMIT_TRUSTED_PROXIES"]
    return [ipaddress.ip_network(e.strip(), strict=False) for e in raw.split(",") if e.strip()]


@pytest.fixture(scope="module")
def nginx_ip(compose):
    return ipaddress.ip_address(
        compose["services"]["nginx"]["networks"]["frontend"]["ipv4_address"]
    )


class TestProxyIsPinned:
    def test_nginx_declares_a_fixed_frontend_address(self, compose):
        # Assert the key's presence here rather than relying on the fixture
        # raising KeyError, so a missing pin is a failure with a message.
        frontend = compose["services"]["nginx"]["networks"]["frontend"]
        assert isinstance(frontend, dict) and "ipv4_address" in frontend, (
            "nginx has no pinned ipv4_address; RATE_LIMIT_TRUSTED_PROXIES "
            "cannot name a stable peer"
        )

    def test_that_address_is_private(self, nginx_ip):
        assert nginx_ip.is_private

    def test_that_address_is_inside_the_declared_subnet(self, compose, nginx_ip):
        subnet = ipaddress.ip_network(
            compose["networks"]["frontend"]["ipam"]["config"][0]["subnet"]
        )
        assert nginx_ip in subnet


class TestTrustMatchesTheProxy:
    def test_mcp_server_declares_a_trusted_proxy(self, trusted):
        # Empty would mean keying on the socket peer, which behind this nginx is
        # a single service-wide bucket.
        assert trusted, "RATE_LIMIT_TRUSTED_PROXIES is empty in docker-compose.yml"

    def test_it_covers_the_nginx_address(self, trusted, nginx_ip):
        assert any(nginx_ip in net for net in trusted), (
            f"nginx at {nginx_ip} is not covered by {[str(n) for n in trusted]}"
        )

    def test_it_is_no_wider_than_the_proxy_itself(self, trusted):
        # A range wider than the proxy lets neighbouring containers, VPN clients
        # or LAN hosts assert an arbitrary X-Real-IP and mint rate-limit buckets.
        total = sum(net.num_addresses for net in trusted)
        assert total == 1, (
            f"trusts {total} addresses; expected exactly the proxy. "
            f"Got {[str(n) for n in trusted]}"
        )

    def test_every_entry_is_a_single_host(self, trusted):
        # Version-agnostic: /32 for IPv4, /128 for IPv6. An earlier form of this
        # test read `prefixlen >= 32 or version == 6`, which passed *any* IPv6
        # network — including fc00::/7, the exact breadth it meant to forbid.
        for net in trusted:
            assert net.prefixlen == net.max_prefixlen, (
                f"{net} spans {net.num_addresses} addresses; expected a single host"
            )


class TestServerIsNotDirectlyExposed:
    def test_mcp_server_publishes_no_host_port(self, compose):
        # The trust model assumes traffic can only arrive via nginx. Publishing a
        # port would let a caller reach the app directly and bypass the proxy.
        assert "ports" not in compose["services"]["mcp-server"], (
            "mcp-server publishes a host port; the proxy is no longer the only path in"
        )
