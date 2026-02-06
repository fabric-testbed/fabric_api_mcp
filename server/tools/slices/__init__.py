"""
Slice tools package for FABRIC MCP Server.

Tools are organized by concern (listing, lifecycle, modification, builder, network) to keep
individual modules focused and make future expansion simpler.
"""
from server.tools.slices import add_to_slice, builder, lifecycle, listing, modify, network
from server.tools.slices.add_to_slice import modify_slice_resources
from server.tools.slices.builder import build_slice
from server.tools.slices.lifecycle import delete_slice, renew_slice
from server.tools.slices.listing import get_slivers, query_slices
from server.tools.slices.modify import accept_modify
from server.tools.slices.network import get_network_info, make_ip_publicly_routable

# Aggregate exported tool callables for FastMCP registration
TOOLS = [
    *listing.TOOLS,
    *lifecycle.TOOLS,
    *modify.TOOLS,
    *builder.TOOLS,
    *network.TOOLS,
    *add_to_slice.TOOLS,
]

__all__ = [
    "listing",
    "lifecycle",
    "modify",
    "builder",
    "network",
    "add_to_slice",
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
