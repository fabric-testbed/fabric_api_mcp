"""
Authentication utilities for Bearer token extraction and validation.
"""
from __future__ import annotations

from typing import Dict, Optional


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
