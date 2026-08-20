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
    claims. Only two things can: constructing a verifier, or publishing
    ``TokenClaims`` into the ``request.state`` slot ``request_claims()`` reads.
    Checking the source is what makes this a real canary — a test that merely
    called ``request_claims()`` on a synthetic request would keep passing after a
    verifying middleware was added, because no middleware would have run.
    """

    #: Markers for the two mechanisms. Matched against identifiers, imports and
    #: non-docstring literals only — the docstrings in rate_limit.py describe
    #: this machinery in prose, and describing it is not wiring it.
    VERIFIER_MARKERS = frozenset(
        {
            "CredMgrVerifier",
            "fabric_mcp_common.auth.verify",
            "CLAIMS_STATE_ATTR",
            "fabric_token_claims",
        }
    )

    @staticmethod
    def _code_symbols(source: str) -> set[str]:
        """Identifiers, imported names and live string literals — no docstrings."""
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

        symbols: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                symbols.add(node.id)
            elif isinstance(node, ast.Attribute):
                symbols.add(node.attr)
            elif isinstance(node, ast.alias):
                symbols.add(node.name)
                symbols.add((node.asname or "").strip())
            elif isinstance(node, ast.ImportFrom):
                symbols.add(node.module or "")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstrings:
                    symbols.add(node.value)
        return {s for s in symbols if s}

    @classmethod
    def _package_sources(cls):
        import pathlib

        import fabric_api_mcp

        root = pathlib.Path(fabric_api_mcp.__file__).resolve().parent
        return {p: p.read_text() for p in root.rglob("*.py")}

    def test_the_canary_detects_wiring_when_present(self):
        # A guard that cannot fire is worse than none, so prove it fires.
        wired = "from fabric_mcp_common.auth.verify import CredMgrVerifier\nv = CredMgrVerifier()\n"
        assert self.VERIFIER_MARKERS & self._code_symbols(wired)

    def test_the_canary_ignores_prose(self):
        prose = '"""Enabling it needs CredMgrVerifier on request.state.fabric_token_claims."""\n'
        assert not (self.VERIFIER_MARKERS & self._code_symbols(prose))

    def test_package_does_not_produce_verified_claims(self):
        hits = {
            path.name: sorted(self.VERIFIER_MARKERS & self._code_symbols(text))
            for path, text in self._package_sources().items()
            if self.VERIFIER_MARKERS & self._code_symbols(text)
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
