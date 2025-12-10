"""
Slice lifecycle tools for FABRIC MCP Server.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from server.dependencies.fabric_manager import get_fabric_manager
from server.log_helper.decorators import tool_logger
from server.utils.async_helpers import call_threadsafe


@tool_logger("create-slice")
async def create_slice(
    name: str,
    graph_model: str,
    ssh_keys: List[str],
    lifetime: Optional[int] = None,
    lease_start_time: Optional[str] = None,
    lease_end_time: Optional[str] = None,
    ctx: Any = None,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Create a new FABRIC slice.

    Args:
        name: Name of the slice to create.
        graph_model: Slice topology graph model (GRAPHML, JSON, etc.).
        ssh_keys: List of SSH public keys for slice access.
        lifetime: Optional slice lifetime in days.
        lease_start_time: Optional lease start time (UTC format).
        lease_end_time: Optional lease end time (UTC format).

    Returns:
        List of sliver dictionaries representing the created slice resources.
    """
    fm, id_token = get_fabric_manager()
    slivers = await call_threadsafe(
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


@tool_logger("renew-slice")
async def renew_slice(
    slice_id: str,
    lease_end_time: str,
    ctx: Any = None,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Renew a FABRIC slice lease.

    Args:
        slice_id: UUID of the slice to renew.
        lease_end_time: New lease end time (UTC format).
    """
    fm, id_token = get_fabric_manager()
    await call_threadsafe(
        fm.renew_slice,
        id_token=id_token,
        slice_id=slice_id,
        lease_end_time=lease_end_time,
    )
    return {"status": "ok", "slice_id": slice_id, "lease_end_time": lease_end_time}


@tool_logger("delete-slice")
async def delete_slice(
    ctx: Any = None,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    slice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Delete a FABRIC slice.

    Args:
        slice_id: Optional UUID of the slice to delete.
    """
    fm, id_token = get_fabric_manager()
    await call_threadsafe(
        fm.delete_slice,
        id_token=id_token,
        slice_id=slice_id,
    )
    return {"status": "ok", "slice_id": slice_id}


TOOLS = [create_slice, renew_slice, delete_slice]
