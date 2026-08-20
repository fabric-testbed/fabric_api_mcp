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


class TestPerUserLimitingIsUnavailable:
    """The README states per-user rate limiting is unavailable, and why.

    These are facts about behaviour and dependencies, checked directly. An
    earlier version of this file tried to enforce the claim by scanning package
    source for signs that a verifier had been wired. That was removed: keying on
    bare names collided with our own dependencies (the MCP SDK exports its own
    unrelated ``TokenVerifier``), and gating on "does this module import
    fabric_mcp_common" inverted the intent — the gate was open in exactly the 7
    modules holding the real code, and closed in the other 31, so it was
    permissive where it mattered and blind everywhere else. A per-file import
    check cannot express a whole-package property.

    What replaces it is a comment on the ``claims.verified`` guard in
    ``_rate_limit_key``: anyone enabling verification edits that line, and it
    points at the README section to update.
    """

    def test_request_claims_does_not_verify_signatures(self):
        # Why step 1 of the key ordering never fires today: the helper the key
        # uses performs an unverified payload decode. A hand-built JWT with a
        # junk signature is accepted, and reported as unverified.
        import base64
        import json

        from fabric_mcp_common.integrations.starlette import request_claims

        def b64(data):
            return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

        token = f"{b64({'alg': 'RS256'})}.{b64({'sub': 'forged'})}.not-a-signature"

        class _Request:
            def __init__(self):
                self.headers = {"authorization": f"Bearer {token}"}

        claims = request_claims(_Request())
        assert claims.sub == "forged"
        assert claims.verified is False

    def test_claims_verified_is_not_assignable(self):
        # Documents that an existing TokenClaims cannot be flipped: `verified` is
        # a read-only property. Relevant because the README explains what
        # enabling verification would actually require.
        from fabric_mcp_common.auth import TokenClaims

        with pytest.raises(AttributeError):
            TokenClaims({"sub": "x"}).verified = True

    def test_the_request_state_slot_is_the_documented_mechanism(self):
        # The README tells an implementer to publish verified claims to
        # request.state.fabric_token_claims. Assert that request_claims() really
        # consults that slot, so the instruction cannot rot into fiction.
        from fabric_mcp_common.auth import TokenClaims
        from fabric_mcp_common.integrations.starlette import (
            CLAIMS_STATE_ATTR,
            request_claims,
        )

        class _State:
            pass

        class _Request:
            def __init__(self):
                self.state = _State()
                self.headers = {}

        request = _Request()
        setattr(request.state, CLAIMS_STATE_ATTR, TokenClaims({"sub": "u"}, verified=True))
        claims = request_claims(request)
        assert claims.verified is True
        assert claims.sub == "u"

    @staticmethod
    def _declared_extras(text: str) -> set:
        """Extras requested of fabric_mcp_common anywhere in a manifest.

        Parsed rather than substring-matched: a naive `"[verify]" in text` check
        misses `[metrics,verify]`, which is how it would realistically be
        written.
        """
        import re

        extras = set()
        for group in re.findall(r"fabric[_-]mcp[_-]common\s*\[([^\]]*)\]", text):
            extras |= {e.strip() for e in group.split(",") if e.strip()}
        return extras

    def test_the_extras_parser_sees_a_combined_group(self):
        assert "verify" in self._declared_extras("fabric_mcp_common[metrics,verify]>=0.1.0")
        assert "verify" in self._declared_extras("fabric-mcp-common[verify]")
        assert "verify" not in self._declared_extras("fabric_mcp_common[metrics]>=0.1.0")

    def test_verify_extra_is_not_a_declared_dependency(self):
        # An unambiguous, stable signal: the [verify] extra is what would make
        # CredMgrVerifier importable at all. No source heuristics involved.
        import pathlib

        import fabric_api_mcp

        repo = pathlib.Path(fabric_api_mcp.__file__).resolve().parent.parent
        for name in ("pyproject.toml", "requirements.txt"):
            manifest = repo / name
            if manifest.is_file():
                assert "verify" not in self._declared_extras(manifest.read_text()), (
                    f"{name} pulls in the verify extra: per-user rate limiting may now "
                    "be reachable, so update the README's 'Per-user limiting' section "
                    "and the _rate_limit_key docstring."
                )


class TestPackageSurface:
    def test_auth_exports_only_the_resolver(self):
        import fabric_api_mcp.auth as auth

        # Token primitives moved to fabric_mcp_common.auth; re-exporting them
        # here again would resurrect the shim this package just shed.
        assert sorted(auth.__all__) == ["optional_token", "require_token", "resolver"]

    def test_version_is_available(self):
        import fabric_api_mcp

        assert fabric_api_mcp.__version__.count(".") == 2
