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


class TestNoVerifierIsWired:
    """The README states per-user rate limiting is unavailable and why.

    That claim rests on nothing in this package producing signature-verified
    claims. Three routes can:

    1. constructing a verifier (``CredMgrVerifier``, or anything satisfying the
       ``TokenVerifier`` protocol) and passing it as ``verifier=`` to
       ``build_resolver`` / ``TokenResolver``;
    2. building ``TokenClaims(..., verified=True)`` directly;
    3. publishing claims into the ``request.state`` slot ``request_claims()``
       consults first.

    Checking the *source* is what makes this a real canary. A test that merely
    called ``request_claims()`` on a synthetic request would keep passing after a
    verifying middleware was added, because no middleware would have run — that
    was the first version. The second version only looked for named verifier
    types, so route 1 slipped past whenever the verifier was a custom protocol
    implementation.
    """

    #: Names that appear only when verification is being wired. ``TokenVerifier``
    #: is here because ``build_resolver(verifier=...)`` accepts *any* object
    #: satisfying that protocol — verification can be enabled without ever
    #: naming CredMgrVerifier, which an earlier version of this canary missed.
    VERIFIER_NAMES = frozenset(
        {
            "CredMgrVerifier",
            "TokenVerifier",
            "fabric_mcp_common.auth.verify",
            "CLAIMS_STATE_ATTR",
        }
    )

    #: Keyword arguments that switch verification on. Matched structurally with
    #: the value inspected: ``claims.verified`` is a legitimate *read* — it is
    #: the guard in _rate_limit_key — whereas ``verified=True`` asserts it.
    VERIFIER_KWARGS = frozenset({"verifier", "verified", "verify"})

    #: The request.state slot request_claims() consults first.
    CLAIMS_SLOT = "fabric_token_claims"

    @classmethod
    def _verification_findings(cls, source: str) -> set[str]:
        """Signs that *source* wires verification, ignoring prose."""
        import ast

        tree = ast.parse(source)

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", None)
                if (
                    body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    docstrings.add(id(body[0].value))

        findings: set[str] = set()
        for node in ast.walk(tree):
            # 1. Named verifier types, the verify module.
            if isinstance(node, ast.Name) and node.id in cls.VERIFIER_NAMES:
                findings.add(node.id)
            elif isinstance(node, ast.alias) and node.name in cls.VERIFIER_NAMES:
                findings.add(node.name)
            elif isinstance(node, ast.ImportFrom) and node.module in cls.VERIFIER_NAMES:
                findings.add(node.module)
            elif isinstance(node, ast.Attribute):
                # 2. The state slot, in any position: `request.state.<slot> =`
                #    is the spelling the README documents, and it is an
                #    attribute, not a string. Matching only the literal missed it.
                if node.attr in (cls.CLAIMS_SLOT, *cls.VERIFIER_NAMES):
                    findings.add(node.attr)
                # 3. Post-construction mutation: TokenResolver keeps .verifier
                #    and .verify, so assigning them enables verification just as
                #    a constructor argument would. Store context only, so the
                #    `claims.verified` *read* in _rate_limit_key does not fire.
                elif node.attr in cls.VERIFIER_KWARGS and isinstance(node.ctx, ast.Store):
                    findings.add(f".{node.attr}=")
            # 4. The slot as a string literal, e.g. via setattr(), outside a
            #    docstring.
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value == cls.CLAIMS_SLOT
                and id(node) not in docstrings
            ):
                findings.add(cls.CLAIMS_SLOT)
            # 5. Enabling keywords — value checked, so an explicit opt-out
            #    (verifier=None, verify=False) does not register.
            elif isinstance(node, ast.keyword) and node.arg in cls.VERIFIER_KWARGS:
                disabled = isinstance(node.value, ast.Constant) and node.value.value in (
                    False,
                    None,
                )
                if not disabled:
                    findings.add(f"{node.arg}=")
        return findings

    @classmethod
    def _package_sources(cls):
        import pathlib

        import fabric_api_mcp

        root = pathlib.Path(fabric_api_mcp.__file__).resolve().parent
        return {p: p.read_text() for p in root.rglob("*.py")}

    def test_canary_catches_a_named_verifier(self):
        wired = "from fabric_mcp_common.auth.verify import CredMgrVerifier\nv = CredMgrVerifier()\n"
        assert self._verification_findings(wired)

    def test_canary_catches_a_verifier_injected_into_the_resolver(self):
        # The path the first version of this canary missed entirely:
        # build_resolver takes any TokenVerifier, so verification can be wired
        # without CredMgrVerifier appearing anywhere.
        wired = "r = build_resolver(local_mode=False, verifier=MyOwnVerifier())\n"
        assert "verifier=" in self._verification_findings(wired)

    def test_canary_catches_a_verifier_typed_only_by_protocol(self):
        wired = "def make(v: TokenVerifier):\n    return v\n"
        assert "TokenVerifier" in self._verification_findings(wired)

    def test_canary_catches_claims_constructed_as_verified(self):
        wired = "c = TokenClaims(payload, verified=True)\n"
        assert "verified=" in self._verification_findings(wired)

    # The state slot has two spellings and an earlier version of this canary
    # only matched the string one — which is also the only one the earlier test
    # exercised. Both are checked now.
    @pytest.mark.parametrize(
        "wired",
        [
            pytest.param(
                "request.state.fabric_token_claims = claims\n", id="attribute-assignment"
            ),
            pytest.param(
                'setattr(request.state, "fabric_token_claims", claims)\n', id="setattr"
            ),
            pytest.param(
                "req.state.fabric_token_claims = TokenClaims(p)\n", id="other-receiver"
            ),
        ],
    )
    def test_canary_catches_a_write_to_the_state_slot(self, wired):
        assert self.CLAIMS_SLOT in self._verification_findings(wired)

    @pytest.mark.parametrize(
        "wired",
        [
            pytest.param("resolver.verifier = SomeVerifier()\n", id="set-verifier"),
            pytest.param("resolver.verify = True\n", id="set-verify-flag"),
        ],
    )
    def test_canary_catches_post_construction_mutation(self, wired):
        # TokenResolver stores .verifier and .verify, so assigning them after
        # construction enables verification exactly as a constructor arg would.
        assert self._verification_findings(wired)

    def test_canary_ignores_reading_the_verified_flag(self):
        # _rate_limit_key does exactly this. It is the guard, not the wiring.
        assert not self._verification_findings(
            "if claims.verified and claims.sub:\n    pass\n"
        )

    def test_canary_ignores_an_explicit_opt_out(self):
        assert not self._verification_findings(
            "r = build_resolver(verifier=None, verify=False)\n"
        )

    def test_canary_ignores_prose(self):
        prose = (
            '"""Needs a CredMgrVerifier published to request.state.fabric_token_claims,\n'
            'or passed as verifier= to build_resolver."""\n'
        )
        assert not self._verification_findings(prose)

    def test_package_does_not_produce_verified_claims(self):
        hits = {
            path.name: sorted(self._verification_findings(text))
            for path, text in self._package_sources().items()
            if self._verification_findings(text)
        }
        assert not hits, (
            f"verification appears to be wired ({hits}). If that is intended, "
            "per-user rate limiting is now reachable — update the README's "
            "'Per-user limiting: what it would take' section and the "
            "_rate_limit_key docstring, which both state it is not."
        )

    @staticmethod
    def _declared_extras(text: str) -> set[str]:
        """Extras requested of fabric_mcp_common anywhere in a manifest.

        Parsed rather than substring-matched: a naive `"[verify]" in text` check
        misses `[metrics,verify]`, which is how it would realistically be
        written. (It did — a mutation test caught this test not guarding its
        claim.)
        """
        import re

        extras: set[str] = set()
        for group in re.findall(r"fabric[_-]mcp[_-]common\s*\[([^\]]*)\]", text):
            extras |= {e.strip() for e in group.split(",") if e.strip()}
        return extras

    def test_the_extras_parser_sees_a_combined_group(self):
        # Prove the parser catches the realistic spelling before trusting it.
        assert "verify" in self._declared_extras("fabric_mcp_common[metrics,verify]>=0.1.0")
        assert "verify" in self._declared_extras("fabric-mcp-common[verify]")
        assert "verify" not in self._declared_extras("fabric_mcp_common[metrics]>=0.1.0")

    def test_verify_extra_is_not_a_declared_dependency(self):
        # The [verify] extra is what would make CredMgrVerifier importable.
        import pathlib

        import fabric_api_mcp

        repo = pathlib.Path(fabric_api_mcp.__file__).resolve().parent.parent
        for name in ("pyproject.toml", "requirements.txt"):
            manifest = repo / name
            if manifest.is_file():
                assert "verify" not in self._declared_extras(manifest.read_text()), (
                    f"{name} pulls in the verify extra; see the note in "
                    "test_package_does_not_produce_verified_claims"
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
