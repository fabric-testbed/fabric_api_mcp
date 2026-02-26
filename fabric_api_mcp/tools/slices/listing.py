"""
Slice listing and inspection tools for FABRIC MCP Server.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

from fastmcp.server.dependencies import get_http_headers

from fabric_api_mcp.auth.token import extract_bearer_token
from fabric_api_mcp.config import config
from fabric_api_mcp.dependencies.fablib_factory import create_fablib_manager
from fabric_api_mcp.log_helper.decorators import tool_logger
from fabric_api_mcp.utils.async_helpers import call_threadsafe
from fabric_api_mcp.utils.data_helpers import normalize_list_param

logger = logging.getLogger(__name__)


def _query_slices_sync(
    id_token: Optional[str],
    as_self: bool,
    slice_id: Optional[str],
    slice_name: Optional[str],
    slice_state: Optional[List[str]],
    exclude_slice_state: Optional[List[str]],
) -> Dict[str, Any]:
    """Synchronous helper that uses FablibManager to list/get slices."""
    from fabrictestbed.slice_manager import SliceState

    fablib = create_fablib_manager(id_token)

    # Single slice lookup by ID or name
    if slice_id or slice_name:
        slice_obj = fablib.get_slice(
            name=slice_name,
            slice_id=slice_id,
            user_only=as_self,
        )
        if slice_obj is None:
            return {}
        d = slice_obj.toDict()
        key = d.get("name") or d.get("id") or "slice"
        return {key: d}

    # Build excludes list for get_slices
    excludes = []
    if exclude_slice_state:
        state_map = {s.name: s for s in SliceState}
        for state_str in exclude_slice_state:
            if state_str in state_map:
                excludes.append(state_map[state_str])
    elif slice_state:
        # If include states are specified, exclude everything else
        include_set = set(slice_state)
        for s in SliceState:
            if s.name not in include_set:
                excludes.append(s)
    # If neither specified, get_slices defaults to excluding Dead and Closing

    slice_objects = fablib.get_slices(
        excludes=excludes if (exclude_slice_state or slice_state) else None,
        user_only=as_self,
    )

    # Build dict keyed by slice name
    out: Dict[str, Any] = {}
    for s in slice_objects:
        d = s.toDict()
        key = d.get("name") or d.get("id")
        if key in out and d.get("id"):
            key = f"{key}-{d['id'][:8]}"
        out[key] = d
    return out


@tool_logger("fabric_query_slices")
async def query_slices(
    as_self: bool = True,
    slice_id: Optional[str] = None,
    slice_name: Optional[str] = None,
    slice_state: Optional[Union[str, List[str]]] = None,
    exclude_slice_state: Optional[Union[str, List[str]]] = None,
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
                     Can be passed as a list or a JSON string.
                     Allowed values: (Nascent, Configuring, StableOK, StableError, ModifyOK, ModifyError, Closing, Dead).
        exclude_slice_state: Optional list of slice states to exclude (e.g., for fetching active slices set exclude_states=["Closing", "Dead"]).
                             Can be passed as a list or a JSON string.
        as_self: If True, list only user's own slices; if False, list all accessible slices.
        limit: Maximum number of slices to return (default: 200).
        offset: Pagination offset (default: 0).
        fetch_all: If True, automatically fetch all pages

    Returns:
        Dictionary of slice data keyed by slice name. Each value is a dict with:
            - id (str): Slice UUID
            - name (str): Slice name
            - state (str): Slice state (e.g., StableOK, Configuring, Dead)
            - lease_start (str): Lease start time (UTC)
            - lease_end (str): Lease end time (UTC)
            - project_id (str): Project UUID
            - email (str): Owner email
            - user_id (str): Owner user UUID

    Display as a Markdown table:

        | Name | State | Lease End | Project ID | Email |
        |------|-------|-----------|------------|-------|
        | my-slice | StableOK | 2025-06-01 00:00:00 +0000 | abc-123 | user@example.com |
    """
    # Normalize list parameters that may be passed as JSON strings
    slice_state = normalize_list_param(slice_state, "slice_state")
    exclude_slice_state = normalize_list_param(exclude_slice_state, "exclude_slice_state")

    headers = get_http_headers(include={"authorization"}) or {}
    id_token = extract_bearer_token(headers)

    return await call_threadsafe(
        _query_slices_sync,
        id_token=id_token,
        as_self=as_self,
        slice_id=slice_id,
        slice_name=slice_name,
        slice_state=slice_state,
        exclude_slice_state=exclude_slice_state,
    )


def _get_slivers_sync(
    id_token: Optional[str],
    slice_id: str,
    as_self: bool,
) -> List[Dict[str, Any]]:
    """Synchronous helper that uses FablibManager to get slivers from a slice."""
    fablib = create_fablib_manager(id_token)
    slice_obj = fablib.get_slice(slice_id=slice_id, user_only=as_self)

    if slice_obj is None:
        raise ValueError(f"Slice not found: id={slice_id}")

    slivers = slice_obj.get_slivers()

    # Convert SliverDTO objects to dicts
    table = []
    for sliver in slivers:
        try:
            reservation_info = json.loads(sliver.sliver["ReservationInfo"])
            error = reservation_info.get("error_message", "")
        except Exception:
            error = ""

        if sliver.sliver_type == "NetworkServiceSliver":
            sliver_type = "network"
        elif sliver.sliver_type == "NodeSliver":
            sliver_type = "node"
        else:
            sliver_type = sliver.sliver_type

        site = sliver.sliver.get("Site", "") if sliver.sliver else ""

        table.append({
            "id": sliver.sliver_id,
            "name": sliver.sliver.get("Name", "") if sliver.sliver else "",
            "site": site,
            "type": sliver_type,
            "state": sliver.state,
            "error": error,
        })

    return table


@tool_logger("fabric_get_slivers")
async def get_slivers(
    slice_id: str,
    as_self: bool = True,
) -> List[Dict[str, Any]]:
    """
    List all slivers (resource allocations) in a slice.

    Args:
        slice_id (str): UUID of the slice containing the slivers.
        as_self: If True, list as owner; if False, list with delegated access.

    Returns:
        List of sliver dicts. Each dict contains:
            - id (str): Sliver/reservation UUID
            - name (str): Sliver name
            - site (str): Site name
            - type (str): "node" or "network" (or raw sliver_type)
            - state (str): Reservation state (e.g., Active, Ticketed, Closed)
            - error (str): Error message if any

    Display as a Markdown table:

        | Name | Type | Site | State | Error |
        |------|------|------|-------|-------|
        | my-node | node | UTAH | Active | |
        | my-net | network | UTAH | Active | |

    Append a summary line: ``3 slivers (1 node, 2 network services)``
    """
    headers = get_http_headers(include={"authorization"}) or {}
    id_token = extract_bearer_token(headers)

    return await call_threadsafe(
        _get_slivers_sync,
        id_token=id_token,
        slice_id=slice_id,
        as_self=as_self,
    )


TOOLS = [query_slices, get_slivers]
