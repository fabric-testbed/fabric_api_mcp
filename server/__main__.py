#!/usr/bin/env python3
"""
FABRIC MCP Server - Refactored

This module implements a Model Context Protocol (MCP) server that exposes FABRIC testbed
API operations as LLM-accessible tools. It provides topology queries, slice management,
and resource operations through a unified FastMCP interface.

Key Features:
- Background caching of topology data (sites, hosts, facility ports, links)
- Bearer token authentication for secure API access
- Structured log_helper with request tracing
- Async tool execution with performance monitoring
- Modular architecture with clean separation of concerns
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastmcp import FastMCP

# Import configuration first
from server.config import config
from server.log_helper.config import configure_logging
from server.dependencies import fabric_manager_factory
from server.errors.handlers import register_error_handlers
from server.middleware.access_log import register_middleware
from server.resources_cache import ResourceCache

# Import log_helper and configure

# Configure log_helper before any other imports
configure_logging()
log = logging.getLogger("fabric.mcp")

# Import other modules

# Import tool implementations and registry
from server.tools import ALL_TOOLS, slices, topology

# Print configuration on startup
config.print_startup_info()

# ---------------------------------------
# MCP App Initialization
# ---------------------------------------
mcp = FastMCP(
    name="fabric-mcp-proxy",
    instructions="Proxy for accessing FABRIC API data via LLM tool calls.",
    version="2.0.0",
)

# ---------------------------------------
# Register Middleware & Error Handlers
# ---------------------------------------
register_middleware(mcp)

# Register error handlers with the FastAPI app
if hasattr(mcp, "app") and mcp.app:
    register_error_handlers(mcp.app)

# ---------------------------------------
# Background Resource Cache
# ---------------------------------------
CACHE = ResourceCache(
    interval_seconds=config.refresh_interval_seconds,
    max_fetch=config.cache_max_fetch,
)

# Wire cache to topology tools
topology.set_cache(CACHE)


def _fm_factory_for_cache():
    """Factory function to create FabricManagerV2 instances for cache refreshes."""
    return fabric_manager_factory.create_for_cache()


async def _on_startup():
    """Start the background cache refresher on application startup."""
    log.info(
        "Starting background cache refresher (interval=%ss, max_fetch=%s)",
        config.refresh_interval_seconds,
        config.cache_max_fetch,
    )
    CACHE.wire_fm_factory(_fm_factory_for_cache)
    await CACHE.start()


async def _on_shutdown():
    """Stop the background cache refresher on application shutdown."""
    log.info("Stopping background cache refresher")
    await CACHE.stop()


# Wire up lifecycle handlers
if hasattr(mcp, "app") and mcp.app:
    mcp.app.add_event_handler("startup", _on_startup)
    mcp.app.add_event_handler("shutdown", _on_shutdown)

# ---------------------------------------
# Register MCP Tools
# ---------------------------------------

# Register all tools declared in server.tools.*.
for tool in ALL_TOOLS:
    mcp.tool(tool)

# ---------------------------------------
# MCP Prompt: fabric-system
# ---------------------------------------
SYSTEM_TEXT = Path(__file__).resolve().parent.joinpath("system.md").read_text(encoding="utf-8").strip()


@mcp.prompt(name="fabric-system")
def fabric_system_prompt():
    """Expose the FABRIC system instructions as an MCP prompt."""
    return SYSTEM_TEXT


# ---------------------------------------
# Server Entry Point
# ---------------------------------------
if __name__ == "__main__":
    # Configure server from environment
    if config.uvicorn_access_log:
        os.environ.setdefault("UVICORN_ACCESS_LOG", "true")
    log.info("Starting FABRIC MCP (FastMCP) on http://%s:%s", config.host, config.port)
    # Run the MCP server with HTTP transport
    mcp.run(transport="http", host=config.host, port=config.port)
