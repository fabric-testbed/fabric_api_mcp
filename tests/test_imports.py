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

    **Scope, deliberately bounded.** It keys on ``verifier`` and never on bare
    ``verify``, which in Python means TLS far more often than token verification
    (``requests.get(url, verify=ca_bundle)``, ``session.verify = path``). That
    costs nothing: ``TokenResolver.resolve`` only verifies when
    ``self.verifier is not None``, so a verifier object is always present when
    verification is genuinely on, and every spelling that supplies one is
    matched. Matching ``verify`` broadly would fail CI on unrelated HTTPS work,
    and a false alarm that blocks an innocent change is worse than the gap.

    This is a heuristic over source text, so it is a prompt to re-read the docs,
    not a security boundary. The real guards — forged subjects, forged headers,
    deployment wiring — do not depend on it.
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

    #: Provenance gate. Nothing here is FABRIC token verification unless it came
    #: from this package, and every name involved is a word other libraries use:
    #: a scan of site-packages found ``TokenVerifier`` 18 times in the ``mcp``
    #: SDK (an unrelated OAuth concept, and a direct dependency of this server),
    #: ``verifier=`` in authlib's OAuth1 client, and ``.verifier=`` in cffi.
    #: Matching on bare names would fail CI the moment this package type-hints
    #: MCP's own TokenVerifier.
    FMC_ROOT = "fabric_mcp_common"

    #: Names specific enough to mean *token* verification — but only when bound
    #: from FMC_ROOT (see above).
    #:
    #: Bare ``verify`` and bare ``verified`` are excluded entirely, being
    #: ambiguous in this domain: ``verify`` is TLS vocabulary
    #: (``requests.get(url, verify=ca_bundle)``) and ``verified`` is
    #: account/email vocabulary (``user.verified = True``) in a server that
    #: serves user records.
    #:
    #: ``_verified`` is included: it is TokenClaims' private slot, and assigning
    #: it is the only way to flip an existing instance — ``claims.verified`` is a
    #: read-only property, so ``claims.verified = True`` raises AttributeError
    #: and is not a route at all.
    ENABLING_NAMES = frozenset({"verifier", "_verified"})

    #: Ambiguous keywords, each meaningful only in a call to one of these
    #: constructors. Resolved through local aliases, subclasses and rebindings,
    #: so `TokenClaims as TC` and `class MyClaims(TokenClaims)` count too — a
    #: literal name check missed all of those.
    KWARG_SCOPES = {
        # verify=True without a verifier raises ValueError in TokenResolver, and
        # resolve() verifies only when self.verifier is not None — so a verifier
        # is always present when verification is genuinely on.
        "verify": frozenset({"build_resolver", "TokenResolver"}),
        # Scoped too: `verifier=` is OAuth1's protocol parameter in authlib, so
        # an unscoped match fired on client.parse_authorization_response(verifier=…)
        # in a module that merely imports from this package.
        "verifier": frozenset({"build_resolver", "TokenResolver"}),
        "verified": frozenset({"TokenClaims"}),
    }

    @classmethod
    def _fmc_bindings(cls, tree) -> set[str]:
        """Local names bound to something imported from fabric_mcp_common.

        This is the provenance gate: ``TokenVerifier`` imported from the MCP SDK
        is a different thing from ``TokenVerifier`` imported from here, and only
        the latter is a sign of FABRIC token verification.
        """
        import ast

        # (original name, local name) pairs. Keeping the original is what lets a
        # seed be looked up by canonical name when the import was aliased —
        # `TokenClaims as TC` binds "TC", and intersecting canonical names with
        # local names alone produced an empty seed and a silent canary.
        pairs: set[tuple[str, str]] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] == cls.FMC_ROOT:
                    for alias in node.names:
                        pairs.add((alias.name, alias.asname or alias.name))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root == cls.FMC_ROOT:
                        pairs.add((root, alias.asname or root))
        return pairs

    @classmethod
    def _seed(cls, canonical, pairs) -> frozenset:
        """Local names for *canonical* symbols actually imported from the package."""
        return frozenset(local for original, local in pairs if original in canonical)

    @staticmethod
    def _local_aliases(tree, canonical) -> set[str]:
        """Every local name that reaches *canonical*.

        Follows ``import X as Y``, ``Y = X`` rebindings and ``class Y(X)``
        subclasses, transitively, so scoping a keyword to a constructor is not
        defeated by renaming it.
        """
        import ast

        names = set(canonical)
        changed = True
        while changed:
            changed = False
            for node in ast.walk(tree):
                found = None
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        if alias.name.split(".")[-1] in names:
                            found = alias.asname or alias.name.split(".")[-1]
                            if found not in names:
                                names.add(found)
                                changed = True
                elif isinstance(node, ast.Assign):
                    src = getattr(node.value, "id", None) or getattr(
                        node.value, "attr", None
                    )
                    if src in names:
                        for target in node.targets:
                            name = getattr(target, "id", None)
                            if name and name not in names:
                                names.add(name)
                                changed = True
                elif isinstance(node, ast.ClassDef):
                    for base in node.bases:
                        base_name = getattr(base, "id", None) or getattr(
                            base, "attr", None
                        )
                        if base_name in names and node.name not in names:
                            names.add(node.name)
                            changed = True
        return names

    #: The request.state slot request_claims() consults first.
    CLAIMS_SLOT = "fabric_token_claims"

    #: Prepended to every snippet below, because a real module in this package
    #: imports from the library. It is applied to the *silence* cases too, so
    #: those assert something: without it they would pass merely by failing the
    #: provenance gate, which is not what they are meant to prove.
    #: Mirrors what a real module here imports. Deliberately does *not* import
    #: TokenVerifier: a module that imported both this package's TokenVerifier
    #: and the MCP SDK's under the same local name would be genuinely ambiguous,
    #: and no static analysis could separate them. Snippets that need it import
    #: it themselves.
    FMC_PRELUDE = (
        "from fabric_mcp_common.auth import TokenClaims\n"
        "from fabric_mcp_common.auth.resolver import TokenResolver\n"
        "from fabric_mcp_common.integrations.fastmcp import build_resolver\n"
    )

    #: Literals worth matching, for dynamic writes like
    #: ``setattr(resolver, "verifier", V())`` or
    #: ``setattr(claims, "_verified", True)``.
    ENABLING_LITERALS = frozenset({"verifier", "_verified"})

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

        def enabled(value) -> bool:
            """False for an explicit opt-out (verifier=None, verified=False)."""
            return not (isinstance(value, ast.Constant) and value.value in (False, None))

        # Ambiguous keywords count only inside the calls that give them their
        # token meaning. Collected first because the walk below reaches keyword
        # nodes without their enclosing Call.
        # Only names that came from fabric_mcp_common can mean FABRIC token
        # verification. Seeding the alias search from that set is what keeps the
        # MCP SDK's own TokenVerifier, authlib's OAuth1 verifier= and cffi's
        # self.verifier out of the results.
        fmc = cls._fmc_bindings(tree)
        scopes = {
            arg: cls._local_aliases(tree, cls._seed(canonical, fmc))
            for arg, canonical in cls.KWARG_SCOPES.items()
        }
        fmc_verifier_names = cls._local_aliases(
            tree, cls._seed(cls.VERIFIER_NAMES, fmc)
        )

        scoped_kwargs: set[int] = set()
        unpacked: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            # functools.partial(TokenClaims, verified=True) and friends: the
            # constructor arrives as an argument rather than the call target.
            arg_names = {
                getattr(a, "id", None) or getattr(a, "attr", None) for a in node.args
            }
            for kw in node.keywords:
                allowed = scopes.get(kw.arg)
                if allowed and (target in allowed or arg_names & allowed):
                    if enabled(kw.value):
                        scoped_kwargs.add(id(kw))
                # `**{"verified": True}` — the keyword has no arg name, so the
                # enabling flag hides inside a dict literal.
                elif kw.arg is None and isinstance(kw.value, ast.Dict):
                    for key, value in zip(kw.value.keys, kw.value.values):
                        if (
                            isinstance(key, ast.Constant)
                            and key.value in cls.KWARG_SCOPES
                            and enabled(value)
                            and (
                                target in scopes[key.value]
                                or arg_names & scopes[key.value]
                            )
                        ):
                            unpacked.add(f"**{key.value}")

        # Everything except the slot name is gated on provenance. The slot,
        # `fabric_token_claims`, is specific enough to stand alone — the
        # site-packages scan found no use of it outside this project.
        gated = bool(fmc)

        findings: set[str] = set(unpacked)
        for node in ast.walk(tree):
            # 1. Verifier types and the verify module, bound from this package.
            if isinstance(node, ast.Name) and node.id in fmc_verifier_names:
                findings.add(node.id)
            elif isinstance(node, ast.ImportFrom) and node.module in cls.VERIFIER_NAMES:
                findings.add(node.module)
            elif isinstance(node, ast.Attribute):
                # 2. The state slot in any position: `request.state.<slot> =` is
                #    the spelling the README documents, and it is an attribute,
                #    not a string.
                if node.attr == cls.CLAIMS_SLOT or node.attr in fmc_verifier_names:
                    findings.add(node.attr)
                # 3. Post-construction mutation of .verifier / ._verified. Store
                #    context only, so the `claims.verified` read in
                #    _rate_limit_key does not fire. `.verify` and `.verified` are
                #    excluded as ambiguous — see ENABLING_NAMES. Gated, because
                #    cffi assigns self.verifier for something else entirely.
                elif (
                    gated
                    and node.attr in cls.ENABLING_NAMES
                    and isinstance(node.ctx, ast.Store)
                ):
                    findings.add(f".{node.attr}=")
            # 4. The slot, or "verifier", as a literal outside a docstring. This
            #    is what covers dynamic writes: setattr(resolver, "verifier", V()),
            #    vars(r)["verifier"] = V(), r.__dict__["verifier"] = V().
            elif (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and (
                    node.value == cls.CLAIMS_SLOT
                    or (gated and node.value in cls.ENABLING_LITERALS)
                )
            ):
                findings.add(node.value)
            # 5. Keywords: all three are scoped to the calls that give them their
            #    token meaning, so TLS `verify=`, OAuth1 `verifier=` and
            #    account `verified=` elsewhere are ignored.
            elif isinstance(node, ast.keyword) and id(node) in scoped_kwargs:
                if enabled(node.value):
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
        assert self._verification_findings(self.FMC_PRELUDE + wired)

    def test_canary_catches_a_verifier_injected_into_the_resolver(self):
        # The path the first version of this canary missed entirely:
        # build_resolver takes any TokenVerifier, so verification can be wired
        # without CredMgrVerifier appearing anywhere.
        wired = "r = build_resolver(local_mode=False, verifier=MyOwnVerifier())\n"
        assert "verifier=" in self._verification_findings(self.FMC_PRELUDE + wired)

    def test_canary_catches_a_verifier_typed_only_by_protocol(self):
        wired = (
            "from fabric_mcp_common.auth.resolver import TokenVerifier\n"
            "def make(v: TokenVerifier):\n    return v\n"
        )
        assert "TokenVerifier" in self._verification_findings(self.FMC_PRELUDE + wired)

    def test_canary_catches_claims_constructed_as_verified(self):
        wired = "c = TokenClaims(payload, verified=True)\n"
        assert "verified=" in self._verification_findings(self.FMC_PRELUDE + wired)

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
        assert self.CLAIMS_SLOT in self._verification_findings(self.FMC_PRELUDE + wired)

    # TokenResolver stores .verifier and .verify, so setting them after
    # construction enables verification exactly as a constructor arg would.
    # Every write route is listed: the attribute-store rule alone missed the
    # dynamic ones, which all go through a string literal instead.
    @pytest.mark.parametrize(
        "wired",
        [
            pytest.param("resolver.verifier = SomeVerifier()\n", id="attribute"),
            pytest.param(
                'setattr(resolver, "verifier", SomeVerifier())\n', id="setattr"
            ),
            pytest.param('vars(resolver)["verifier"] = V()\n', id="vars-subscript"),
            pytest.param(
                'resolver.__dict__["verifier"] = V()\n', id="dunder-dict-subscript"
            ),
            pytest.param(
                'object.__setattr__(resolver, "verifier", V())\n', id="object-setattr"
            ),
            # The only way to flip an existing TokenClaims: `verified` is a
            # read-only property, so `claims.verified = True` raises
            # AttributeError and is not a route at all.
            pytest.param("claims._verified = True\n", id="private-slot"),
            pytest.param(
                'setattr(claims, "_verified", True)\n', id="private-slot-setattr"
            ),
        ],
    )
    def test_canary_catches_post_construction_mutation(self, wired):
        assert self._verification_findings(self.FMC_PRELUDE + wired), f"missed: {wired.strip()}"

    @pytest.mark.parametrize(
        "wired",
        [
            pytest.param(
                "r = build_resolver(local_mode=False, verifier=V(), verify=True)\n",
                id="verify-in-build_resolver",
            ),
            pytest.param(
                "c = TokenClaims(payload, verified=True)\n", id="verified-in-TokenClaims"
            ),
            # Scoping by literal name missed every one of these.
            pytest.param(
                "from fabric_mcp_common.auth import TokenClaims as TC\n"
                "c = TC(payload, verified=True)\n",
                id="aliased-import",
            ),
            pytest.param(
                "TC = TokenClaims\nc = TC(payload, verified=True)\n", id="rebinding"
            ),
            pytest.param(
                "class MyClaims(TokenClaims):\n    pass\n"
                "c = MyClaims(payload, verified=True)\n",
                id="subclass",
            ),
            pytest.param(
                "TC = TokenClaims\nTC2 = TC\nc = TC2(p, verified=True)\n",
                id="transitive-rebinding",
            ),
            pytest.param(
                "f = functools.partial(TokenClaims, verified=True)\n",
                id="functools-partial",
            ),
            pytest.param(
                'c = TokenClaims(p, **{"verified": True})\n', id="dict-unpacking"
            ),
            pytest.param(
                "from fabric_mcp_common.integrations.fastmcp import build_resolver as br\n"
                "r = br(local_mode=False, verify=True)\n",
                id="aliased-resolver-factory",
            ),
        ],
    )
    def test_ambiguous_keywords_count_in_their_own_calls(self, wired):
        assert self._verification_findings(self.FMC_PRELUDE + wired), f"missed: {wired.strip()}"

    def test_claims_verified_is_not_assignable(self):
        # Justifies excluding `.verified=`: matching it would guard a route that
        # cannot exist, while blocking legitimate `user.verified = True`.
        from fabric_mcp_common.auth import TokenClaims

        with pytest.raises(AttributeError):
            TokenClaims({"sub": "x"}).verified = True

    # A false alarm here blocks unrelated work, so these matter as much as the
    # catches. `verify` in Python is overwhelmingly TLS vocabulary, and this
    # package talks to FABRIC over HTTPS.
    @pytest.mark.parametrize(
        "benign",
        [
            pytest.param("requests.get(url, verify=True)\n", id="requests-verify-true"),
            pytest.param(
                'requests.get(url, verify="/etc/ssl/ca.pem")\n', id="requests-verify-path"
            ),
            pytest.param("httpx.Client(verify=ssl_context)\n", id="httpx-verify-ctx"),
            pytest.param(
                'session.verify = "/etc/ssl/ca.pem"\n', id="session-verify-attribute"
            ),
            pytest.param('payload = {"status": "verified"}\n', id="verified-in-payload"),
            pytest.param('action = "verify"\n', id="verify-as-a-string"),
            pytest.param("if claims.verified:\n    pass\n", id="reading-the-guard"),
            pytest.param(
                "r = build_resolver(verifier=None, verify=False)\n", id="explicit-opt-out"
            ),
            # `verified` is account/email vocabulary too, in a server that serves
            # user and project records.
            pytest.param("user.verified = True\n", id="user-verified-attribute"),
            pytest.param("u = UserRecord(verified=True)\n", id="user-record-kwarg"),
            pytest.param(
                'return {"email": e, "verified": True}\n', id="verified-response-field"
            ),
            pytest.param("email_verified = claims.get('email_verified')\n", id="oidc-claim"),
            pytest.param('setattr(user, "verified", True)\n', id="user-setattr"),
            # Alias resolution must not leak: importing TokenClaims for a type
            # hint does not make an unrelated constructor a claims constructor.
            pytest.param(
                "from fabric_mcp_common.auth import TokenClaims\n"
                "def f(c: TokenClaims):\n"
                "    return UserRecord(verified=True)\n",
                id="claims-imported-for-typing-only",
            ),
            pytest.param(
                'from fabric_mcp_common.auth import TokenClaims as TC\n'
                'u = UserRecord(verified=True)\n',
                id="aliased-import-unrelated-constructor",
            ),
            # Found by scanning site-packages: the MCP SDK — a direct dependency
            # of this server — has its own unrelated TokenVerifier, 18 times.
            pytest.param(
                "from mcp.server.auth.provider import TokenVerifier\n"
                "def f(v: TokenVerifier):\n    return v\n",
                id="mcp-sdk-token-verifier",
            ),
            # Also found by that scan: verifier= is OAuth1's protocol parameter.
            pytest.param(
                "r = client.parse_authorization_response(verifier=v)\n",
                id="oauth1-verifier-kwarg",
            ),
            pytest.param(
                "code_verifier = generate_code_verifier()\n", id="pkce-code-verifier"
            ),
        ],
    )
    def test_canary_does_not_fire_on_unrelated_code(self, benign):
        found = self._verification_findings(self.FMC_PRELUDE + benign)
        assert not found, f"false positive on {benign.strip()!r}: {sorted(found)}"

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
