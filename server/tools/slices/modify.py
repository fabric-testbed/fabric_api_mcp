"""
Slice modification tools for FABRIC MCP Server.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastmcp.server.context import Context

from server.dependencies.fabric_manager import get_fabric_manager
from server.log_helper.decorators import tool_logger
from server.utils.async_helpers import call_threadsafe


@tool_logger("modify-slice")
async def modify_slice(
    ctx: Context,
    slice_id: str,
    graph_model: str,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Modify an existing FABRIC slice topology.

    Args:
        slice_id: UUID of the slice to modify.
        graph_model: Updated slice topology graph model.

    Returns:
        List of sliver dictionaries with modification results.
    """
    fm, id_token = get_fabric_manager()
    slivers = await call_threadsafe(
        fm.modify_slice,
        id_token=id_token,
        slice_id=slice_id,
        graph_model=graph_model,
        return_fmt="dict",
    )
    return slivers


@tool_logger("accept-modify")
async def accept_modify(
    ctx: Context,
    slice_id: str,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Accept pending slice modifications.

    Args:
        slice_id: UUID of the slice with pending modifications.

    Returns:
        Slice dictionary with updated state.
    """
    fm, id_token = get_fabric_manager()
    accepted = await call_threadsafe(
        fm.accept_modify,
        id_token=id_token,
        slice_id=slice_id,
        return_fmt="dict",
    )
    return accepted


TOOLS = [modify_slice, accept_modify]
