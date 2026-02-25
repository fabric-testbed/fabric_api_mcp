"""
Slice lifecycle tools for FABRIC MCP Server.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fabric_api_mcp.dependencies.fabric_manager import get_fabric_manager
from fabric_api_mcp.log_helper.decorators import tool_logger
from fabric_api_mcp.utils.async_helpers import call_threadsafe


@tool_logger("fabric_renew_slice")
async def renew_slice(
    slice_id: str,
    lease_end_time: str,
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


@tool_logger("fabric_delete_slice")
async def delete_slice(
    slice_id: str,
) -> Dict[str, Any]:
    """
    Delete a FABRIC slice.

    Args:
        slice_id: UUID of the slice to delete.
    """
    fm, id_token = get_fabric_manager()
    await call_threadsafe(
        fm.delete_slice,
        id_token=id_token,
        slice_id=slice_id,
    )
    return {"status": "ok", "slice_id": slice_id}


TOOLS = [renew_slice, delete_slice]
