"""
Slice modification tools for FABRIC MCP Server.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from server.dependencies.fabric_manager import get_fabric_manager
from server.log_helper.decorators import tool_logger
from server.utils.async_helpers import call_threadsafe


@tool_logger("accept-modify")
async def accept_modify(
    
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


TOOLS = [accept_modify]
