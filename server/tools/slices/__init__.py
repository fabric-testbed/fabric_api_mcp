"""
Slice tools package for FABRIC MCP Server.

Tools are organized by concern (listing, lifecycle, modification, builder, network) to keep
individual modules focused and make future expansion simpler.
"""
from server.tools.slices import create, lifecycle, listing, modify, network
from server.tools.slices.modify import modify_slice_resources, accept_modify
from server.tools.slices.create import build_slice
from server.tools.slices.lifecycle import delete_slice, renew_slice
from server.tools.slices.listing import get_slivers, query_slices
from server.tools.slices.network import get_network_info, make_ip_publicly_routable

# Aggregate exported tool callables for FastMCP registration
TOOLS = [
    *listing.TOOLS,
    *lifecycle.TOOLS,
    *create.TOOLS,
    *modify.TOOLS,
    *network.TOOLS,
]

__all__ = [
    "listing",
    "lifecycle",
    "modify",
    "create",
    "network",
    "query_slices",
    "get_slivers",
    "renew_slice",
    "delete_slice",
    "accept_modify",
    "build_slice",
    "make_ip_publicly_routable",
    "get_network_info",
    "modify_slice_resources",
    "TOOLS",
]
