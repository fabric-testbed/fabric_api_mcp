"""
Authentication for the FABRIC MCP Server.

Token handling itself lives in ``fabric_mcp_common.auth``; import from there
directly for primitives such as ``decode_token_claims``, ``extract_bearer_token``,
``read_token_from_file`` or ``redact_token``.  What remains here is the part that
is specific to this server: a resolver bound to its configuration.
"""
from fabric_api_mcp.auth.resolver import optional_token, require_token, resolver

__all__ = [
    "optional_token",
    "require_token",
    "resolver",
]
