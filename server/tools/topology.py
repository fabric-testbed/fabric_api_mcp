"""
Topology query tools for FABRIC MCP Server.

These tools query FABRIC topology resources (sites, hosts, facility ports, links)
with caching support for improved performance.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from server.config import config
from server.dependencies.fabric_manager import get_fabric_manager
from server.log_helper.decorators import tool_logger
from server.utils.async_helpers import call_threadsafe
from server.utils.data_helpers import apply_sort, paginate

# Reference to global cache (will be set by __main__.py)
CACHE = None


def set_cache(cache):
    """Set the global cache instance for topology tools."""
    global CACHE
    CACHE = cache


@tool_logger("query-sites")
async def query_sites(
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Query FABRIC sites with optional filtering, sorting, and pagination."""
    # Try to use cached data first
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.sites) if snap.sites else None

    if items is None:
        # Cache miss - fetch from API
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_sites, id_token=id_token, filters=filters, limit=fm_limit, offset=0
        )
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


@tool_logger("query-hosts")
async def query_hosts(
    
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Query FABRIC hosts with optional filtering, sorting, and pagination."""
    # Try cache first, fall back to API on cache miss
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.hosts) if snap.hosts else None

    if items is None:
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_hosts, id_token=id_token, filters=filters, limit=fm_limit, offset=0
        )
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


@tool_logger("query-facility-ports")
async def query_facility_ports(
    
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Query FABRIC facility ports with optional filtering, sorting, and pagination."""
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.facility_ports) if snap.facility_ports else None

    if items is None:
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_facility_ports, id_token=id_token, filters=filters, limit=fm_limit, offset=0
        )
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


@tool_logger("query-links")
async def query_links(
    
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Query FABRIC network links with optional filtering, sorting, and pagination."""
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.links) if snap.links else None

    if items is None:
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_links, id_token=id_token, filters=filters, limit=fm_limit, offset=0
        )
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


# Populate exported tools list
TOOLS = [
    query_sites,
    query_hosts,
    query_facility_ports,
    query_links,
]
