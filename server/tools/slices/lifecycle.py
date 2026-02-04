"""
Slice lifecycle tools for FABRIC MCP Server.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from server.dependencies.fabric_manager import get_fabric_manager
from server.log_helper.decorators import tool_logger
from server.utils.async_helpers import call_threadsafe
from server.utils.data_helpers import normalize_list_param


@tool_logger("renew-slice")
async def renew_slice(
    slice_id: str,
    lease_end_time: str,
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


TOOLS = [renew_slice, delete_slice]
