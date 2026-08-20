"""
Backward-compatible re-exports of the token helpers.

The implementation now lives in the standalone ``fabric_mcp_common.auth`` package so
that other MCP servers can reuse it.  This module remains as a thin shim for
existing imports; new code should import from ``fabric_mcp_common.auth`` directly, or
use the shared resolver in :mod:`fabric_api_mcp.auth.resolver`.
"""
from __future__ import annotations

from typing import Optional

from fabric_mcp_common.auth import (
    MissingTokenError,
    TokenClaims,
    decode_token_claims,
    extract_bearer_token,
    read_token_from_file,
    redact_token,
)

__all__ = [
    "MissingTokenError",
    "TokenClaims",
    "decode_token_claims",
    "extract_bearer_token",
    "read_token_from_file",
    "redact_token",
    "validate_token_presence",
]


def validate_token_presence(token: Optional[str]) -> str:
    """
    Validate that a token is present.

    Args:
        token: Token string or None

    Returns:
        The validated token string

    Raises:
        MissingTokenError: If token is None or empty.  Subclasses ``ValueError``
            and carries the same message as before, so existing handlers and
            error payloads are unchanged.
    """
    if not token:
        raise MissingTokenError()
    return token
