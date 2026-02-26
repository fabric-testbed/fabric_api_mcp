"""
Authentication utilities for Bearer token extraction and validation.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Dict, Optional

log = logging.getLogger("fabric.mcp")


def decode_token_claims(token: str) -> Dict[str, str]:
    """
    Base64-decode the JWT payload (middle segment) without cryptographic verification.

    Upstream FABRIC APIs handle token validation; this is only for extracting
    user identity claims for logging purposes.

    Args:
        token: A JWT string (header.payload.signature)

    Returns:
        Dict with 'sub', 'email', 'name' claims if present, or {} on failure.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        # Add padding for base64url decoding
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return {
            k: payload[k]
            for k in ("sub", "email", "name")
            if k in payload
        }
    except Exception:
        log.debug("Failed to decode JWT claims", exc_info=True)
        return {}


def extract_bearer_token(headers: Dict[str, str]) -> Optional[str]:
    """
    Extract Bearer token from HTTP Authorization header.

    Args:
        headers: Dictionary of HTTP headers (case-insensitive)

    Returns:
        Token string if found, None otherwise
    """
    # Make headers case-insensitive by converting to lowercase
    low = {k.lower(): v for k, v in headers.items()}
    auth = low.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def read_token_from_file() -> str:
    """
    Read the FABRIC token from the file specified by FABRIC_TOKEN_LOCATION.

    The token file is a JSON file containing the raw token string.

    Returns:
        Token string read from the file

    Raises:
        ValueError: If FABRIC_TOKEN_LOCATION is not set or the file cannot be read
    """
    token_location = os.environ.get("FABRIC_TOKEN_LOCATION")
    if not token_location:
        raise ValueError("FABRIC_TOKEN_LOCATION environment variable is not set")

    try:
        with open(token_location, "r") as f:
            token_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Failed to read token from {token_location}: {e}")

    if isinstance(token_data, str):
        return token_data
    if isinstance(token_data, dict) and "id_token" in token_data:
        return token_data["id_token"]
    raise ValueError(f"Unexpected token format in {token_location}")


def validate_token_presence(token: Optional[str]) -> str:
    """
    Validate that a token is present.

    Args:
        token: Token string or None

    Returns:
        The validated token string

    Raises:
        ValueError: If token is None or empty
    """
    if not token:
        raise ValueError("Authentication Required: Missing or invalid Authorization Bearer token.")
    return token
