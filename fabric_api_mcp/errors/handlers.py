"""
Error handlers for FastAPI application.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from fabric_api_mcp.errors.exceptions import FabricMCPError, AuthenticationError, ClientError

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger("fabric.mcp")


async def fabric_error_handler(request: Request, exc: FabricMCPError) -> JSONResponse:
    """
    Convert FabricMCPError exceptions to JSON responses.

    Args:
        request: The HTTP request that triggered the error
        exc: The FABRIC MCP error that was raised

    Returns:
        JSONResponse with error details
    """
    # Authentication and client errors return 400, others return 500
    status_code = 400 if isinstance(exc, (AuthenticationError, ClientError)) else 500

    # Log error for monitoring
    log.error(
        "Error handling request: %s",
        exc.details,
        extra={
            "error_type": exc.error_type,
            "path": request.url.path,
            "method": request.method,
        },
    )

    return JSONResponse(
        status_code=status_code,
        content=exc.to_dict(),
    )


async def pydantic_validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    """
    Convert Pydantic validation errors to JSON responses.

    Args:
        request: The HTTP request that triggered the error
        exc: The Pydantic validation error

    Returns:
        JSONResponse with validation error details
    """
    log.warning(
        "Validation error: %s",
        str(exc),
        extra={
            "path": request.url.path,
            "method": request.method,
            "validation_errors": exc.errors(),
        },
    )

    return JSONResponse(
        status_code=400,
        content={
            "error": "client_error",
            "details": f"Validation error: {str(exc)}",
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    """
    Register all error handlers with the FastAPI application.

    Args:
        app: The FastAPI application instance
    """
    app.add_exception_handler(FabricMCPError, fabric_error_handler)
    app.add_exception_handler(ValidationError, pydantic_validation_error_handler)
