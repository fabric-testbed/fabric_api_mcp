"""
The server's shared token resolver.

One resolver, built from the server's mode, is used by every protected code
path.  In server mode it reads the request's ``Authorization: Bearer`` header
and nothing else — a local token file must never be used to serve someone
else's request.  In local/stdio mode it reads the token file named by
``FABRIC_TOKEN_LOCATION``.
"""
from __future__ import annotations

import logging
from typing import Optional

from fabric_mcp_common.auth import MissingTokenError
from fabric_mcp_common.integrations.fastmcp import build_resolver, current_token

from fabric_api_mcp.config import config

log = logging.getLogger("fabric.mcp")

#: Shared resolver for protected calls.  Resolves per call, so a rotated token
#: file or a new request's header is always picked up.
resolver = build_resolver(
    local_mode=config.local_mode,
    allow_header_in_local_mode=False,
)


def require_token() -> str:
    """Return the caller's token.

    Raises:
        MissingTokenError: If the caller supplied no usable token.  Subclasses
            ``ValueError``, so existing handlers still catch it.
    """
    try:
        return resolver.require_token()
    except MissingTokenError:
        # Emitted on the "fabric.mcp" logger with the original wording, so
        # existing log-based alerting on this line keeps matching.
        log.warning("Missing Authorization header on protected call")
        raise


def optional_token() -> Optional[str]:
    """Return the in-flight request's bearer token, or ``None``.

    Header-only by design: tools pass the result straight to
    :func:`~fabric_api_mcp.dependencies.fablib_factory.create_fablib_manager`,
    which sources credentials from ``fabric_rc`` in local mode and requires an
    explicit token in server mode.
    """
    return current_token()


__all__ = ["optional_token", "require_token", "resolver"]
