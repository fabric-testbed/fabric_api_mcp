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

import asyncio
import atexit
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP

# Import configuration first
from fabric_api_mcp.config import config
from fabric_api_mcp.log_helper.config import configure_logging
from fabric_api_mcp.dependencies import fabric_manager_factory
from fabric_api_mcp.middleware.access_log import AccessLogMiddleware
from fabric_api_mcp.resources_cache import ResourceCache

# Import log_helper and configure

# Configure log_helper before any other imports
configure_logging()
log = logging.getLogger("fabric.mcp")

# Import other modules

# Import tool implementations
from fabric_api_mcp.tools import slices, topology
from fabric_api_mcp.tools.topology import query_sites, query_hosts, query_facility_ports, query_links
from fabric_api_mcp.tools.slices.listing import query_slices, get_slivers
from fabric_api_mcp.tools.slices.create import build_slice
from fabric_api_mcp.tools.slices.modify import modify_slice_resources, accept_modify
from fabric_api_mcp.tools.slices.lifecycle import renew_slice, delete_slice, post_boot_config
from fabric_api_mcp.tools.slices.network import make_ip_publicly_routable, get_network_info
from fabric_api_mcp.tools.slices.inspect import list_nodes, list_networks, list_interfaces
from fabric_api_mcp.tools.projects import (
    show_my_projects, list_project_users, get_user_keys,
    get_bastion_username, get_user_info, add_public_key,
    remove_public_key, os_reboot,
)

# Print configuration on startup
config.print_startup_info()

# ---------------------------------------
# Background Resource Cache
# ---------------------------------------
CACHE = ResourceCache(
    interval_seconds=config.refresh_interval_seconds,
    max_fetch=config.cache_max_fetch,
)


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


@asynccontextmanager
async def _cache_lifespan(server: FastMCP):
    """FastMCP lifespan: start/stop the resource cache."""
    await _on_startup()
    try:
        yield
    finally:
        await _on_shutdown()


# ---------------------------------------
# MCP App Initialization
# ---------------------------------------
mcp = FastMCP(
    name="fabric-mcp-proxy",
    instructions="Proxy for accessing FABRIC API data via LLM tool calls.",
    version="2.0.0",
    lifespan=_cache_lifespan if config.transport == "http" else None,
)

# ---------------------------------------
# Register custom HTTP routes & build middleware stack (HTTP only)
# ---------------------------------------
# NOTE: FastMCP creates the ASGI app lazily inside mcp.run(). The `mcp.app`
# attribute does NOT exist at import time.  Use `mcp.custom_route` for HTTP
# endpoints and pass Starlette `Middleware` instances via `mcp.run(middleware=...)`.

# Middleware list passed to mcp.run() — assembled at import time, applied at run time
_http_middleware: list = []

if config.transport == "http":
    from starlette.middleware import Middleware

    # Access log middleware (always in server mode)
    _http_middleware.append(Middleware(AccessLogMiddleware))

    if config.metrics_enabled:
        from fabric_api_mcp.middleware.metrics import MetricsMiddleware
        from fabric_api_mcp.middleware.security_metrics import SecurityMetricsMiddleware

        _http_middleware.append(Middleware(MetricsMiddleware))
        _http_middleware.append(Middleware(SecurityMetricsMiddleware))

        # Prometheus /metrics endpoint via FastMCP custom_route (queued, applied at run time)
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import Response
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

        @mcp.custom_route("/metrics", methods=["GET"], name="prometheus_metrics", include_in_schema=False)
        async def prometheus_metrics(request: StarletteRequest) -> Response:
            return Response(
                content=generate_latest(),
                media_type=CONTENT_TYPE_LATEST,
            )

# Wire cache to topology tools
topology.set_cache(CACHE)

# ---------------------------------------
# Tool Registry with Names & Annotations
# ---------------------------------------
# Each entry maps a tool function to its registered name and MCP annotations.
# Annotations: readOnlyHint (T=read-only), destructiveHint (T=destructive),
#              idempotentHint (T=safe to retry), openWorldHint (T=external interaction)
TOOL_REGISTRY = [
    # Topology (read-only, idempotent)
    {
        "fn": query_sites,
        "name": "fabric_query_sites",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": query_hosts,
        "name": "fabric_query_hosts",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": query_facility_ports,
        "name": "fabric_query_facility_ports",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": query_links,
        "name": "fabric_query_links",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    # Slice listing (read-only, idempotent)
    {
        "fn": query_slices,
        "name": "fabric_query_slices",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": get_slivers,
        "name": "fabric_get_slivers",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    # Slice creation / modification (write)
    {
        "fn": build_slice,
        "name": "fabric_build_slice",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "fn": modify_slice_resources,
        "name": "fabric_modify_slice",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "fn": accept_modify,
        "name": "fabric_accept_modify",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    # Slice lifecycle
    {
        "fn": renew_slice,
        "name": "fabric_renew_slice",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": delete_slice,
        "name": "fabric_delete_slice",
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "fn": post_boot_config,
        "name": "fabric_post_boot_config",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    # Slice inspection (read-only, idempotent)
    {
        "fn": list_nodes,
        "name": "fabric_list_nodes",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": list_networks,
        "name": "fabric_list_networks",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": list_interfaces,
        "name": "fabric_list_interfaces",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    # Network tools
    {
        "fn": get_network_info,
        "name": "fabric_get_network_info",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": make_ip_publicly_routable,
        "name": "fabric_make_ip_routable",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    # Project / user tools (read-only, idempotent)
    {
        "fn": show_my_projects,
        "name": "fabric_show_projects",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": list_project_users,
        "name": "fabric_list_project_users",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": get_user_keys,
        "name": "fabric_get_user_keys",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": get_bastion_username,
        "name": "fabric_get_bastion_username",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": get_user_info,
        "name": "fabric_get_user_info",
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    # POA key management (write)
    {
        "fn": add_public_key,
        "name": "fabric_add_public_key",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
    },
    {
        "fn": remove_public_key,
        "name": "fabric_remove_public_key",
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "fn": os_reboot,
        "name": "fabric_os_reboot",
        "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
    },
]

# Register all tools with FastMCP using explicit names and annotations
for entry in TOOL_REGISTRY:
    mcp.tool(entry["fn"], name=entry["name"], annotations=entry["annotations"])

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
def main():
    """Entry point for the fabric-mcp console script and python -m server."""
    if config.transport == "stdio":
        # Local mode: start cache manually and register cleanup via atexit
        log.info("Starting FABRIC MCP (FastMCP) in local/stdio mode")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(_on_startup())

        def _cleanup():
            loop.run_until_complete(_on_shutdown())
            loop.close()

        atexit.register(_cleanup)
        mcp.run(transport="stdio")
    else:
        # Server mode: HTTP transport — pass Starlette middleware and use
        # FastMCP's lifespan for cache start/stop.
        if config.uvicorn_access_log:
            os.environ.setdefault("UVICORN_ACCESS_LOG", "true")
        log.info("Starting FABRIC MCP (FastMCP) on http://%s:%s", config.host, config.port)
        mcp.run(
            transport="http",
            host=config.host,
            port=config.port,
            middleware=_http_middleware or None,
        )


if __name__ == "__main__":
    main()
