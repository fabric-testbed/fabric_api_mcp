"""
Slice listing and inspection tools for FABRIC MCP Server.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from server.dependencies.fabric_manager import get_fabric_manager
from server.log_helper.decorators import tool_logger
from server.utils.async_helpers import call_threadsafe


@tool_logger("query-slices")
async def query_slices(
    ctx: Any = None,
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
) -> Dict[str, Any]:
    """
    List FABRIC slices with optional filtering.

    Args:
        slice_id: slice GUID
        slice_name: slice name
        slice_state: Optional list of slice states to include (e.g., ["StableError", "StableOK"]).
                     Allowed values: (Nascent, Configuring, StableOK, StableError, ModifyOK, ModifyError, Closing, Dead).
        exclude_slice_state: Optional list of slice states to exclude (e.g., for fetching active slices set exclude_states=["Closing", "Dead"]).
        as_self: If True, list only user's own slices; if False, list all accessible slices.
        limit: Maximum number of slices to return (default: 200).
        offset: Pagination offset (default: 0).
        fetch_all: If True, automatically fetch all pages

    Returns:
        Dictionary of slice data with slice name as the key.
    """
    fm, id_token = get_fabric_manager()

    # Single slice lookup by ID
    if slice_id:
        item = await call_threadsafe(
            fm.get_slice,
            id_token=id_token,
            slice_id=slice_id,
            graph_format="GRAPHML",
            as_self=as_self,
            return_fmt="dict",
        )
        key = item.get("name") or item.get("slice_id") or "slice"
        return {key: item}

    # List slices with optional pagination
    results: List[Dict[str, Any]] = []
    cur_offset = offset
    while True:
        page = await call_threadsafe(
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
        # Client-side filtering for excluded states
        if exclude_slice_state:
            exclude_set = set(exclude_slice_state)
            page = [p for p in page if (p.get("state") not in exclude_set)]
        results.extend(page)
        if not fetch_all or len(page) < limit:
            break
        cur_offset += limit

    # Build dict keyed by slice name (handle duplicates)
    out: Dict[str, Any] = {}
    for s in results:
        key = s.get("name") or s.get("slice_id")
        if key in out and s.get("slice_id"):
            key = f"{key}-{s['slice_id'][:8]}"
        out[key] = s
    return out


@tool_logger("get-slivers")
async def get_slivers(
    ctx: Any = None,
    slice_id: str,
    as_self: bool = True,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List all slivers (resource allocations) in a slice.

    Args:
        slice_id: UUID of the slice containing the slivers.
        as_self: If True, list as owner; if False, list with delegated access.

    Returns:
        List of sliver dictionaries for sliver data.
    """
    fm, id_token = get_fabric_manager()
    slivers = await call_threadsafe(
        fm.list_slivers,
        id_token=id_token,
        slice_id=slice_id,
        as_self=as_self,
        return_fmt="dict",
    )
    return slivers


TOOLS = [query_slices, get_slivers]
