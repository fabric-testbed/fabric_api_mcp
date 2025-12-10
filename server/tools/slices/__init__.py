"""
Slice tools package for FABRIC MCP Server.

Tools are organized by concern (listing, lifecycle, modification) to keep
individual modules focused and make future expansion simpler.
"""
from server.tools.slices import lifecycle, listing, modify
from server.tools.slices.lifecycle import create_slice, delete_slice, renew_slice
from server.tools.slices.listing import get_slivers, query_slices
from server.tools.slices.modify import accept_modify, modify_slice

# Aggregate exported tool callables for FastMCP registration
TOOLS = [
    *listing.TOOLS,
    *lifecycle.TOOLS,
    *modify.TOOLS,
]

__all__ = [
    "listing",
    "lifecycle",
    "modify",
    "query_slices",
    "get_slivers",
    "create_slice",
    "renew_slice",
    "delete_slice",
    "modify_slice",
    "accept_modify",
    "TOOLS",
]
