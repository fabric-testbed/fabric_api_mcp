#!/usr/bin/env python3
from __future__ import annotations

import os
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple

from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.server.dependencies import get_http_headers

from fim.user import GraphFormat

from fabrictestbed.fabric_manager_v2 import FabricManagerV2

# ---------------------------------------
# Config (env with sensible defaults)
# ---------------------------------------
FABRIC_ORCHESTRATOR_HOST = os.environ.get("FABRIC_ORCHESTRATOR_HOST", "orchestrator.fabric-testbed.net")
FABRIC_CREDMGR_HOST      = os.environ.get("FABRIC_CREDMGR_HOST", "cm.fabric-testbed.net")
FABRIC_AM_HOST           = os.environ.get("FABRIC_AM_HOST", "artifacts.fabric-testbed.net")
FABRIC_CORE_API_HOST     = os.environ.get("FABRIC_CORE_API_HOST", "uis.fabric-testbed.net")

print(f"Orchestrator HOST: {FABRIC_ORCHESTRATOR_HOST}")
print(f"Credmgr HOST: {FABRIC_CREDMGR_HOST}")
print(f"Artifact Manager HOST: {FABRIC_AM_HOST}")
print(f"Core API HOST: {FABRIC_CORE_API_HOST}")

# ---------------------------------------
# MCP App
# ---------------------------------------
mcp = FastMCP(
    name="fabric-mcp-proxy",
    instructions="Proxy for accessing FABRIC API data via LLM tool calls.",
    version="2.0.0",
)

SYSTEM_TEXT = Path("system.md").read_text(encoding="utf-8").strip()

@mcp.prompt(name="fabric-system")
def fabric_system_prompt():
    return SYSTEM_TEXT

# ---------------------------------------
# Helpers
# ---------------------------------------
def _bearer_from_headers(headers: Dict[str, str]) -> Optional[str]:
    low = {k.lower(): v for k, v in headers.items()}
    auth = low.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None

def _fabric_manager() -> Tuple[FabricManagerV2, str]:
    headers = get_http_headers() or {}
    token = _bearer_from_headers(headers)
    if not token:
        raise ValueError("Authentication Required: Missing or invalid Authorization Bearer token.")
    fm = FabricManagerV2(
        credmgr_host=FABRIC_CREDMGR_HOST,
        orchestrator_host=FABRIC_ORCHESTRATOR_HOST,
        logger=log,
        http_debug=bool(int(os.environ.get("HTTP_DEBUG", "0"))),
    )
    return fm, token

async def _call_threadsafe(fn, **kwargs):
    return await asyncio.to_thread(fn, **{k: v for k, v in kwargs.items() if v is not None})

# ---------- NEW: Topology query tools + helpers ----------

def _apply_sort(items: List[Dict[str, Any]], sort: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    sort = {"field": "cores_available", "direction": "desc"}  # asc|desc
    """
    if not sort or not isinstance(sort, dict):
        return items
    field = sort.get("field")
    if not field:
        return items
    direction = (sort.get("direction") or "asc").lower()
    reverse = direction == "desc"
    # Missing field -> None (sorted last)
    return sorted(items, key=lambda r: (r.get(field) is None, r.get(field)), reverse=reverse)

def _paginate(items: List[Dict[str, Any]], limit: Optional[int], offset: int) -> List[Dict[str, Any]]:
    start = max(0, int(offset or 0))
    if limit is None:
        return items[start:]
    return items[start : start + max(0, int(limit))]

# Note: We do filtering within FabricManagerV2.query_* already via the filters dict.
# To support sorting, we ask FM for a reasonably large page when sort is requested,
# then apply sort+paginate here. Cap to avoid abuse.
_MAX_FETCH_FOR_SORT = int(os.environ.get("MAX_FETCH_FOR_SORT", "5000"))

@mcp.tool(
    name="query-sites",
    title="Query Sites",
    description=(
        "List sites with filters and optional sorting.\n"
        "filters: dict supporting operators eq, ne, lt, lte, gt, gte, in, contains, icontains, regex, any, all, and 'or'.\n"
        "sort: {\"field\": \"name|cores_available|...\", \"direction\": \"asc|desc\"}"
    ),
)
async def query_sites(
    ctx: Context,
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    fm, id_token = _fabric_manager()
    fm_limit = _MAX_FETCH_FOR_SORT if sort else limit
    items = await _call_threadsafe(
        fm.query_sites, id_token=id_token, filters=filters, limit=fm_limit, offset=0
    )
    items = _apply_sort(items, sort)
    return _paginate(items, limit=limit, offset=offset)

@mcp.tool(
    name="query-hosts",
    title="Query Hosts",
    description=(
        "List hosts with filters and optional sorting. "
        "Filter on fields like site, name, cores_* / ram_* / disk_* or nested components (client-side contains/regex).\n"
        "filters: operator dicts; sort: {\"field\": \"cores_available\", \"direction\": \"desc\"}"
    ),
)
async def query_hosts(
    ctx: Context,
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    fm, id_token = _fabric_manager()
    fm_limit = _MAX_FETCH_FOR_SORT if sort else limit
    items = await _call_threadsafe(
        fm.query_hosts, id_token=id_token, filters=filters, limit=fm_limit, offset=0
    )
    items = _apply_sort(items, sort)
    return _paginate(items, limit=limit, offset=offset)

@mcp.tool(
    name="query-facility-ports",
    title="Query Facility Ports",
    description=(
        "List facility ports with filters and optional sorting. "
        "Common fields: site, name, vlans, port, switch, labels.\n"
        "filters: operator dicts; sort optional."
    ),
)
async def query_facility_ports(
    ctx: Context,
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    fm, id_token = _fabric_manager()
    fm_limit = _MAX_FETCH_FOR_SORT if sort else limit
    items = await _call_threadsafe(
        fm.query_facility_ports, id_token=id_token, filters=filters, limit=fm_limit, offset=0
    )
    items = _apply_sort(items, sort)
    return _paginate(items, limit=limit, offset=offset)

@mcp.tool(
    name="query-links",
    title="Query Links",
    description=(
        "List L2/L3 links with filters and optional sorting. "
        "Fields: name, layer, labels, bandwidth, endpoints (array of {site,node,port}).\n"
        "Example filter to touch a site: "
        "{\"or\": [{\"name\": {\"icontains\": \"UCSD\"}}, {\"layer\": {\"eq\": \"L2\"}}]}"
    ),
)
async def query_links(
    ctx: Context,
    filters: Optional[Dict[str, Any]] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    fm, id_token = _fabric_manager()
    fm_limit = _MAX_FETCH_FOR_SORT if sort else limit
    items = await _call_threadsafe(
        fm.query_links, id_token=id_token, filters=filters, limit=fm_limit, offset=0
    )
    items = _apply_sort(items, sort)
    return _paginate(items, limit=limit, offset=offset)

# ---------- END NEW ----------

# ---------------------------------------
# Existing tools (your original ones) …
# ---------------------------------------

@mcp.tool(
    name="query-slices",
    title="Query Slices",
    description="Query slices with rich filters. Lists accept multiple values."
)
async def query_slices(
    ctx: Context,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    as_self: bool = True,
    slice_id: Optional[str] = None,
    slice_name: Optional[str] = None,
    slice_state: Optional[List[str]] = None,
    exclude_slice_state: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = 200,
    fetch_all: bool = True,
    graph_format: Optional[str] = str(GraphFormat.GRAPHML),
) -> Dict[str, Any]:
    fm, id_token = _fabric_manager()
    if slice_id:
        item = await _call_threadsafe(
            fm.get_slice,
            id_token=id_token,
            slice_id=slice_id,
            graph_format="GRAPHML",
            as_self=as_self,
            return_fmt="dict",
        )
        key = item.get("name") or item.get("slice_id") or "slice"
        return {key: item}

    results: List[Dict[str, Any]] = []
    cur_offset = offset
    while True:
        page = await _call_threadsafe(
            fm.list_slices,
            id_token=id_token,
            states=slice_state,
            name=slice_name,
            search=None,
            exact_match=False,
            as_self=as_self,
            limit=limit,
            offset=cur_offset,
            return_fmt="dict",
        )
        if not page:
            break
        if exclude_slice_state:
            exclude_set = set(exclude_slice_state)
            page = [p for p in page if (p.get("state") not in exclude_set)]
        results.extend(page)
        if not fetch_all or len(page) < limit:
            break
        cur_offset += limit

    out: Dict[str, Any] = {}
    for s in results:
        key = s.get("name") or s.get("slice_id")
        if key in out and s.get("slice_id"):
            key = f"{key}-{s['slice_id'][:8]}"
        out[key] = s
    return out

@mcp.tool(
    name="get-slivers",
    title="List Slivers for a Slice",
    description="Return all slivers for a given slice_id."
)
async def get_slivers(
    ctx: Context,
    slice_id: str,
    as_self: bool = True,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    fm, id_token = _fabric_manager()
    slivers = await _call_threadsafe(
        fm.list_slivers,
        id_token=id_token,
        slice_id=slice_id,
        as_self=as_self,
        return_fmt="dict",
    )
    return slivers

@mcp.tool(
    name="create-slice",
    title="Create Slice",
    description="Create a slice with a serialized graph model and SSH keys."
)
async def create_slice(
    ctx: Context,
    name: str,
    graph_model: str,
    ssh_keys: List[str],
    lifetime: Optional[int] = None,
    lease_start_time: Optional[str] = None,
    lease_end_time: Optional[str] = None,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    fm, id_token = _fabric_manager()
    slivers = await _call_threadsafe(
        fm.create_slice,
        id_token=id_token,
        name=name,
        graph_model=graph_model,
        ssh_keys=ssh_keys,
        lifetime=lifetime,
        lease_start_time=lease_start_time,
        lease_end_time=lease_end_time,
        return_fmt="dict",
    )
    return slivers

@mcp.tool(
    name="modify-slice",
    title="Modify Slice",
    description="Modify an existing slice to the provided graph model."
)
async def modify_slice(
    ctx: Context,
    slice_id: str,
    graph_model: str,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    fm, id_token = _fabric_manager()
    slivers = await _call_threadsafe(
        fm.modify_slice,
        id_token=id_token,
        slice_id=slice_id,
        graph_model=graph_model,
        return_fmt="dict",
    )
    return slivers

@mcp.tool(
    name="accept-modify",
    title="Accept Last Modify",
    description="Accept the last slice modify and return the accepted slice model."
)
async def accept_modify(
    ctx: Context,
    slice_id: str,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> Dict[str, Any]:
    fm, id_token = _fabric_manager()
    accepted = await _call_threadsafe(
        fm.accept_modify,
        id_token=id_token,
        slice_id=slice_id,
        return_fmt="dict",
    )
    return accepted

@mcp.tool(
    name="renew-slice",
    title="Renew Slice",
    description="Extend a slice to a new lease_end_time (format: 'YYYY-MM-DD HH:MM:SS +0000')."
)
async def renew_slice(
    ctx: Context,
    slice_id: str,
    lease_end_time: str,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> Dict[str, Any]:
    fm, id_token = _fabric_manager()
    await _call_threadsafe(
        fm.renew_slice,
        id_token=id_token,
        slice_id=slice_id,
        lease_end_time=lease_end_time,
    )
    return {"status": "ok", "slice_id": slice_id, "lease_end_time": lease_end_time}

@mcp.tool(
    name="delete-slice",
    title="Delete Slice",
    description="Delete a slice by ID. If slice_id is omitted, deletes all user slices in project (use carefully)."
)
async def delete_slice(
    ctx: Context,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    slice_id: Optional[str] = None,
) -> Dict[str, Any]:
    fm, id_token = _fabric_manager()
    await _call_threadsafe(
        fm.delete_slice,
        id_token=id_token,
        slice_id=slice_id,
    )
    return {"status": "ok", "slice_id": slice_id}

@mcp.tool(
    name="resources",
    title="Query Resources",
    description="Return advertised resources (optionally filtered)."
)
async def resources(
    ctx: Context,
    level: int = 1,
    force_refresh: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    includes: Optional[List[str]] = None,
    excludes: Optional[List[str]] = None,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> Dict[str, Any]:
    fm, id_token = _fabric_manager()
    res = await _call_threadsafe(
        fm.resources,
        id_token=id_token,
        level=level,
        force_refresh=force_refresh,
        start_date=start_date,
        end_date=end_date,
        includes=includes,
        excludes=excludes,
        return_fmt="dict",
    )
    return res

@mcp.tool(
    name="poa-create",
    title="POA Create",
    description="Perform an operational action on a sliver (cpuinfo, numainfo, cpupin, numatune, reboot, addkey, removekey, rescan)."
)
async def poa_create(
    ctx: Context,
    sliver_id: str,
    operation: str,
    vcpu_cpu_map: Optional[List[Dict[str, str]]] = None,
    node_set: Optional[List[str]] = None,
    keys: Optional[List[Dict[str, str]]] = None,
    bdf: Optional[List[str]] = None,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    fm, id_token = _fabric_manager()
    poas = await _call_threadsafe(
        fm.poa_create,
        id_token=id_token,
        sliver_id=sliver_id,
        operation=operation,
        vcpu_cpu_map=vcpu_cpu_map,
        node_set=node_set,
        keys=keys,
        bdf=bdf,
        return_fmt="dict",
    )
    return poas

@mcp.tool(
    name="poa-get",
    title="POA Get",
    description="Get POA statuses by sliver_id or poa_id."
)
async def poa_get(
    ctx: Context,
    sliver_id: Optional[str] = None,
    poa_id: Optional[str] = None,
    states: Optional[List[str]] = None,
    limit: int = 20,
    offset: int = 0,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    fm, id_token = _fabric_manager()
    poas = await _call_threadsafe(
        fm.poa_get,
        id_token=id_token,
        sliver_id=sliver_id,
        poa_id=poa_id,
        states=states,
        limit=limit,
        offset=offset,
        return_fmt="dict",
    )
    return poas

# ---------------------------------------
# Run
# ---------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"Starting FABRIC MCP (FastMCP) on http://{host}:{port}")
    mcp.run(transport="http", host=host, port=port)
