"""
Slice tools package for FABRIC MCP Server.

Tools are organized by concern (listing, lifecycle, modification, builder) to keep
individual modules focused and make future expansion simpler.
"""
from server.tools.slices import builder, lifecycle, listing, modify
from server.tools.slices.builder import build_slice
from server.tools.slices.lifecycle import delete_slice, renew_slice
from server.tools.slices.listing import get_slivers, query_slices
from server.tools.slices.modify import accept_modify, modify_slice

# Aggregate exported tool callables for FastMCP registration
TOOLS = [
    *listing.TOOLS,
    *lifecycle.TOOLS,
    *modify.TOOLS,
    *builder.TOOLS,
]

__all__ = [
    "listing",
    "lifecycle",
    "modify",
    "builder",
    "query_slices",
    "get_slivers",
    "renew_slice",
    "delete_slice",
    "modify_slice",
    "accept_modify",
    "build_slice",
    "TOOLS",
]
