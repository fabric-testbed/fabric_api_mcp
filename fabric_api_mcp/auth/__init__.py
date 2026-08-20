"""
Authentication module for FABRIC MCP Server.

Thin wrapper over the standalone ``fabric_mcp_common.auth`` package.
"""
from fabric_api_mcp.auth.resolver import optional_token, require_token, resolver
from fabric_api_mcp.auth.token import (
    MissingTokenError,
    TokenClaims,
    decode_token_claims,
    extract_bearer_token,
    read_token_from_file,
    redact_token,
    validate_token_presence,
)

__all__ = [
    "MissingTokenError",
    "TokenClaims",
    "decode_token_claims",
    "extract_bearer_token",
    "optional_token",
    "read_token_from_file",
    "redact_token",
    "require_token",
    "resolver",
    "validate_token_presence",
]
