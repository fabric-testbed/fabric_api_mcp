"""
Slice tools package for FABRIC MCP Server.

Tools are organized by concern (listing, lifecycle, modification, builder, network, inspect)
to keep individual modules focused and make future expansion simpler.
"""
from fabric_api_mcp.tools.slices import create, inspect, lifecycle, listing, modify, network
from fabric_api_mcp.tools.slices.modify import modify_slice_resources, accept_modify
from fabric_api_mcp.tools.slices.create import build_slice
from fabric_api_mcp.tools.slices.inspect import list_nodes, list_networks, list_interfaces
from fabric_api_mcp.tools.slices.lifecycle import delete_slice, renew_slice
from fabric_api_mcp.tools.slices.listing import get_slivers, query_slices
from fabric_api_mcp.tools.slices.network import get_network_info, make_ip_publicly_routable

# Aggregate exported tool callables for FastMCP registration
TOOLS = [
    *listing.TOOLS,
    *lifecycle.TOOLS,
    *create.TOOLS,
    *modify.TOOLS,
    *network.TOOLS,
    *inspect.TOOLS,
]

__all__ = [
    "listing",
    "lifecycle",
    "modify",
    "create",
    "network",
    "inspect",
    "query_slices",
    "get_slivers",
    "renew_slice",
    "delete_slice",
    "accept_modify",
    "build_slice",
    "list_nodes",
    "list_networks",
    "list_interfaces",
    "make_ip_publicly_routable",
    "get_network_info",
    "modify_slice_resources",
    "TOOLS",
]
