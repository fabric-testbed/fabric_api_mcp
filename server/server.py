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

from fabrictestbed.fabric_manager_v2 import FabricManagerV2, get_logger

# ---------------------------------------
# Config (env with sensible defaults)
# ---------------------------------------
FABRIC_ORCHESTRATOR_HOST = os.environ.get("FABRIC_ORCHESTRATOR_HOST", "orchestrator.fabric-testbed.net")
FABRIC_CREDMGR_HOST      = os.environ.get("FABRIC_CREDMGR_HOST", "cm.fabric-testbed.net")

# Optional (not used by V3 façade directly, kept for compatibility/logging)
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

# Load your markdown system prompt
SYSTEM_TEXT = Path("system.md").read_text(encoding="utf-8").strip()

@mcp.prompt(name="fabric-system")
def fabric_system_prompt():
    """System rules for querying FABRIC via MCP"""
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
    # Logger once; reuse across calls
    log = get_logger("fabric.mcp", level=os.environ.get("LOG_LEVEL", "INFO"))
    fm = FabricManagerV2(
        credmgr_host=FABRIC_CREDMGR_HOST,
        orchestrator_host=FABRIC_ORCHESTRATOR_HOST,
        logger=log,
        http_debug=bool(int(os.environ.get("HTTP_DEBUG", "0"))),
    )
    return fm, token

async def _call_threadsafe(fn, **kwargs):
    """Run sync function in thread to keep FastAPI/uvicorn loop free."""
    return await asyncio.to_thread(fn, **{k: v for k, v in kwargs.items() if v is not None})

# ---------------------------------------
# Tools
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
    exclude_slice_state: Optional[List[str]] = None,   # kept for back-compat; applied client-side
    offset: int = 0,
    limit: int = 200,
    fetch_all: bool = True,
    graph_format: Optional[str] = str(GraphFormat.GRAPHML),  # not used in list call, kept for parity
) -> Dict[str, Any]:
    """
    Returns a dict keyed by slice name with slice properties (MCP-friendly).
    """
    fm, id_token = _fabric_manager()

    # If slice_id is provided, return that one directly
    if slice_id:
        item = await _call_threadsafe(
            fm.get_slice,
            id_token=id_token,
            slice_id=slice_id,
            graph_format="GRAPHML",  # or pass `graph_format` if you prefer
            as_self=as_self,
            return_fmt="dict",
        )
        # Key the response by name if present, else by slice_id
        key = item.get("name") or item.get("slice_id") or "slice"
        return {key: item}

    # Otherwise, list with optional filters
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
        # Apply exclude state filter client-side if provided
        if exclude_slice_state:
            exclude_set = set(exclude_slice_state)
            page = [p for p in page if (p.get("state") not in exclude_set)]
        results.extend(page)
        if not fetch_all or len(page) < limit:
            break
        cur_offset += limit

    # Map by slice name (fall back to slice_id to avoid collisions/missing names)
    out: Dict[str, Any] = {}
    for s in results:
        key = s.get("name") or s.get("slice_id")
        # In rare collisions, suffix with short id
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
    as_self: bool = True
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
) -> List[Dict[str, Any]]:
    fm, id_token = _fabric_manager()
    poas = await _call_threadsafe(
        fm.poa_create,
        id_token=id_token,
        sliver_id=sliver_id,
        operation=operation,  # validated by orchestrator
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
