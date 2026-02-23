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
from server.models.inputs import (
    QueryFacilityPortsInput,
    QueryHostsInput,
    QueryLinksInput,
    QuerySitesInput,
)
from server.utils.async_helpers import call_threadsafe
from server.utils.data_helpers import apply_filters, apply_sort, paginate

# Reference to global cache (will be set by __main__.py)
CACHE = None


def set_cache(cache):
    """Set the global cache instance for topology tools."""
    global CACHE
    CACHE = cache


@tool_logger("fabric_query_sites")
async def query_sites(
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Query FABRIC sites with optional declarative filtering, sorting, and pagination.

    Site Record Fields:
        - name (str): Site identifier (e.g., "SRI", "RENC", "UCSD")
        - state (str/null): Site state
        - address (str): Physical address
        - location (list): [latitude, longitude]
        - ptp_capable (bool): PTP clock support
        - ipv4_management (bool): IPv4 management support
        - cores_capacity/allocated/available (int): CPU core resources
        - ram_capacity/allocated/available (int): RAM in GB
        - disk_capacity/allocated/available (int): Disk in GB
        - hosts (list[str]): Worker hostnames
        - components (dict): Component details (GPUs, NICs, FPGAs)

    Args:
        filters: Declarative JSON filter DSL. Operators: eq, ne, lt, lte, gt, gte,
                 in, contains, icontains, regex, any, all.
                 Logical OR: {"or": [{...}, {...}]}.
                 contains/icontains work on strings (substring), dicts (key match),
                 and lists (element match).
                 Example: {"cores_available": {"gte": 64}}
        sort: Sort specification {"field": "cores_available", "direction": "desc"}
        limit: Maximum results to return (default: 200)
        offset: Number of results to skip (default: 0)

    Filter Examples:
        {"cores_available": {"gte": 64}}
        {"name": {"in": ["RENC", "UCSD", "STAR"]}}
        {"or": [{"site": {"icontains": "UCSD"}}, {"site": {"icontains": "STAR"}}],
         "cores_available": {"gte": 32}}
        {"components": {"contains": "FPGA"}, "cores_available": {"gte": 30}}

    Returns:
        Dict with items, total, count, offset, has_more
    """
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.sites) if snap.sites else None

    if items is None:
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_sites, id_token=id_token, filters=None, limit=fm_limit, offset=0
        )

    items = apply_filters(items, filters)
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


@tool_logger("fabric_query_hosts")
async def query_hosts(
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Query FABRIC hosts with optional declarative filtering, sorting, and pagination.

    Host Record Fields:
        - name (str): Worker hostname (e.g., "ucsd-w5.fabric-testbed.net")
        - site (str): Site name (e.g., "UCSD", "RENC")
        - cores_capacity/allocated/available (int): CPU core resources
        - ram_capacity/allocated/available (int): RAM in GB
        - disk_capacity/allocated/available (int): Disk in GB
        - components (dict): Component details with capacity/allocated:
            {"GPU-Tesla T4": {"capacity": 2, "allocated": 0},
             "SmartNIC-ConnectX-5": {"capacity": 2, "allocated": 0},
             "NVME-P4510": {"capacity": 4, "allocated": 0}}

    Args:
        filters: Declarative JSON filter DSL.
                 contains/icontains work on strings (substring), dicts (key match),
                 and lists (element match).
                 Example: {"site": {"eq": "UCSD"}, "cores_available": {"gte": 32}}
                 Example: {"components": {"contains": "GPU"}, "cores_available": {"gte": 16}}
        sort: Sort specification {"field": "cores_available", "direction": "desc"}
        limit: Maximum results to return (default: 200)
        offset: Number of results to skip (default: 0)

    Returns:
        Dict with items, total, count, offset, has_more
    """
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.hosts) if snap.hosts else None

    if items is None:
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_hosts, id_token=id_token, filters=None, limit=fm_limit, offset=0
        )

    items = apply_filters(items, filters)
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


@tool_logger("fabric_query_facility_ports")
async def query_facility_ports(
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Query FABRIC facility ports with optional declarative filtering, sorting, and pagination.

    Facility Port Record Fields:
        - site (str): Site name (e.g., "BRIST", "STAR", "UCSD", "GCP")
        - name (str): Facility port name (e.g., "StarLight-400G-1-STAR")
        - port (str): Port identifier (e.g., "SmartInternetLab-BRIST-int")
        - switch (str): Switch port mapping
        - labels (dict): Metadata with vlan_range, region, etc.
        - vlans (str): String representation of VLAN ranges

    Args:
        filters: Declarative JSON filter DSL.
                 Example: {"site": {"in": ["UCSD", "STAR"]}}
        sort: Sort specification {"field": "site", "direction": "asc"}
        limit: Maximum results to return (default: 200)
        offset: Number of results to skip (default: 0)

    Returns:
        Dict with items, total, count, offset, has_more
    """
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.facility_ports) if snap.facility_ports else None

    if items is None:
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_facility_ports, id_token=id_token, filters=None, limit=fm_limit, offset=0
        )

    items = apply_filters(items, filters)
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


@tool_logger("fabric_query_links")
async def query_links(
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Query FABRIC network links with optional declarative filtering, sorting, and pagination.

    Link Record Fields:
        - name (str): Link identifier
        - layer (str): Network layer ("L1" or "L2")
        - labels (dict/null): Additional metadata
        - bandwidth (int): Link bandwidth in Gbps
        - endpoints (list): Connection endpoints [{site, node, port}]

    Args:
        filters: Declarative JSON filter DSL.
                 Example: {"bandwidth": {"gte": 100}, "layer": "L1"}
        sort: Sort specification {"field": "bandwidth", "direction": "desc"}
        limit: Maximum results to return (default: 200)
        offset: Number of results to skip (default: 0)

    Returns:
        Dict with items, total, count, offset, has_more
    """
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.links) if snap.links else None

    if items is None:
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_links, id_token=id_token, filters=None, limit=fm_limit, offset=0
        )

    items = apply_filters(items, filters)
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


# Populate exported tools list
TOOLS = [
    query_sites,
    query_hosts,
    query_facility_ports,
    query_links,
]
