"""
Topology query tools for FABRIC MCP Server.

These tools query FABRIC topology resources (sites, hosts, facility ports, links)
with caching support for improved performance.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from server.config import config
from server.dependencies.fabric_manager import get_fabric_manager
from server.log_helper.decorators import tool_logger
from server.utils.async_helpers import call_threadsafe
from server.utils.data_helpers import apply_sort, paginate

# Reference to global cache (will be set by __main__.py)
CACHE = None


def _coerce_filter(filters: Optional[Any]) -> Optional[Callable[[Dict[str, Any]], bool]]:
    """
    Convert a filter string to a callable, or pass through existing callables/None.

    Accepts lambda strings like "lambda r: r.get('cores_available', 0) >= 64".
    Restricts builtins to a minimal safe set needed by examples.
    """
    if filters is None:
        return None
    if callable(filters):
        return filters
    if not isinstance(filters, str):
        raise TypeError("filters must be a callable or lambda string")

    safe_builtins = {
        "any": any,
        "all": all,
        "len": len,
        "sum": sum,
        "min": min,
        "max": max,
    }

    try:
        fn = eval(filters, {"__builtins__": safe_builtins}, {})
    except Exception as e:
        raise ValueError(f"Invalid filter expression: {filters}") from e

    if not callable(fn):
        raise ValueError("Filter expression must evaluate to a callable")
    return fn


def _apply_filters(items: List[Dict[str, Any]], filters: Optional[Callable[[Dict[str, Any]], bool]]) -> List[Dict[str, Any]]:
    """Apply a filter callable if provided."""
    if not filters:
        return items
    return [r for r in items if filters(r)]


def set_cache(cache):
    """Set the global cache instance for topology tools."""
    global CACHE
    CACHE = cache


@tool_logger("query-sites")
async def query_sites(

    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    filters: Optional[str] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Query FABRIC sites with optional lambda filtering, sorting, and pagination.

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
        filters: Lambda function string, e.g., "lambda r: r.get('cores_available', 0) >= 64"
        sort: Sort specification {"field": "cores_available", "direction": "desc"}
        limit: Maximum results to return (default: 200)
        offset: Number of results to skip (default: 0)

    Filter Examples:
        "lambda r: r.get('cores_available', 0) >= 64"
        "lambda r: r.get('name') in ['RENC', 'UCSD', 'STAR']"
        "lambda r: 'GPU' in r.get('components', {})"
        "lambda r: r.get('cores_available', 0) >= 32 and r.get('ram_available', 0) >= 128"

    Returns:
        List of site records matching the filter
    """
    # Try to use cached data first
    filter_fn = _coerce_filter(filters)
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.sites) if snap.sites else None

    if items is None:
        # Cache miss - fetch from API
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_sites, id_token=id_token, filters=filter_fn, limit=fm_limit, offset=0
        )
    else:
        items = _apply_filters(items, filter_fn)
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


@tool_logger("query-hosts")
async def query_hosts(

    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    filters: Optional[str] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Query FABRIC hosts with optional lambda filtering, sorting, and pagination.

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
        filters: Lambda function string, e.g., "lambda r: r.get('site') == 'UCSD'"
        sort: Sort specification {"field": "cores_available", "direction": "desc"}
        limit: Maximum results to return (default: 200)
        offset: Number of results to skip (default: 0)

    Filter Examples:
        "lambda r: r.get('site') == 'UCSD'"
        "lambda r: r.get('cores_available', 0) >= 32"
        "lambda r: any('GPU' in comp for comp in r.get('components', {}).keys())"
        "lambda r: 'GPU-Tesla T4' in r.get('components', {})"
        "lambda r: r.get('site') == 'UCSD' and r.get('cores_available', 0) >= 32 and any('GPU' in comp for comp in r.get('components', {}).keys())"

    Returns:
        List of host records matching the filter
    """
    # Try cache first, fall back to API on cache miss
    filter_fn = _coerce_filter(filters)
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.hosts) if snap.hosts else None

    if items is None:
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_hosts, id_token=id_token, filters=filter_fn, limit=fm_limit, offset=0
        )
    else:
        items = _apply_filters(items, filter_fn)
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


@tool_logger("query-facility-ports")
async def query_facility_ports(

    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    filters: Optional[str] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Query FABRIC facility ports with optional lambda filtering, sorting, and pagination.

    Facility Port Record Fields:
        - site (str): Site name (e.g., "BRIST", "STAR", "UCSD", "GCP")
        - name (str): Facility port name (e.g., "StarLight-400G-1-STAR")
        - port (str): Port identifier (e.g., "SmartInternetLab-BRIST-int")
        - switch (str): Switch port mapping
        - labels (dict): Metadata with vlan_range, region, etc.
            {"vlan_range": ["3110-3119"], "region": "sjc-zone2-6"}
        - vlans (str): String representation of VLAN ranges (NOTE: STRING, not list!)

    Args:
        filters: Lambda function string, e.g., "lambda r: r.get('site') == 'UCSD'"
        sort: Sort specification {"field": "site", "direction": "asc"}
        limit: Maximum results to return (default: 200)
        offset: Number of results to skip (default: 0)

    Filter Examples:
        "lambda r: r.get('site') == 'UCSD'"
        "lambda r: r.get('site') in ['UCSD', 'STAR', 'BRIST']"
        "lambda r: 'StarLight' in r.get('name', '')"
        "lambda r: '400G' in r.get('name', '')"
        "lambda r: '3110-3119' in r.get('labels', {}).get('vlan_range', [])"
        "lambda r: r.get('site') in ['GCP', 'AWS', 'AZURE']"

    Returns:
        List of facility port records matching the filter
    """
    filter_fn = _coerce_filter(filters)
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.facility_ports) if snap.facility_ports else None

    if items is None:
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_facility_ports, id_token=id_token, filters=filter_fn, limit=fm_limit, offset=0
        )
    else:
        items = _apply_filters(items, filter_fn)
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


@tool_logger("query-links")
async def query_links(

    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    filters: Optional[str] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Query FABRIC network links with optional lambda filtering, sorting, and pagination.

    Link Record Fields:
        - name (str): Link identifier (e.g., "link:local-port+losa-data-sw:HundredGigE0/0/0/15...")
        - layer (str): Network layer ("L1" or "L2")
        - labels (dict/null): Additional metadata
        - bandwidth (int): Link bandwidth in Gbps
        - endpoints (list): Connection endpoints
            [{"site": null, "node": "uuid", "port": "HundredGigE0/0/0/15.3370"},
             {"site": null, "node": "uuid", "port": "TenGigE0/0/0/22/0.3370"}]
            Note: site is typically null; node is a UUID

    Args:
        filters: Lambda function string, e.g., "lambda r: r.get('bandwidth', 0) >= 100"
        sort: Sort specification {"field": "bandwidth", "direction": "desc"}
        limit: Maximum results to return (default: 200)
        offset: Number of results to skip (default: 0)

    Filter Examples:
        "lambda r: r.get('bandwidth', 0) >= 100"
        "lambda r: r.get('layer') == 'L1'"
        "lambda r: r.get('layer') == 'L2'"
        "lambda r: any('HundredGigE' in ep.get('port', '') for ep in r.get('endpoints', []))"
        "lambda r: 'ucsd-data-sw' in r.get('name', '').lower()"
        "lambda r: 'losa-data-sw' in r.get('name', '').lower() and 'ucsd-data-sw' in r.get('name', '').lower()"

    Returns:
        List of link records matching the filter
    """
    filter_fn = _coerce_filter(filters)
    items = None
    if CACHE:
        snap = CACHE.snapshot()
        items = list(snap.links) if snap.links else None

    if items is None:
        fm, id_token = get_fabric_manager()
        fm_limit = config.max_fetch_for_sort if sort else limit
        items = await call_threadsafe(
            fm.query_links, id_token=id_token, filters=filter_fn, limit=fm_limit, offset=0
        )
    else:
        items = _apply_filters(items, filter_fn)
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


# Populate exported tools list
TOOLS = [
    query_sites,
    query_hosts,
    query_facility_ports,
    query_links,
]
