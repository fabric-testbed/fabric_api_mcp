"""
MCP tools for FABRIC MCP Server.

This module exposes a simple registry (`ALL_TOOLS`) so new tools can be added
by appending to each module's or package's `TOOLS` list rather than wiring
them manually in __main__.py.
"""
from fabric_api_mcp.tools import slices, topology, projects

# List of all tool callables that should be registered with FastMCP
ALL_TOOLS = [
    *topology.TOOLS,
    *slices.TOOLS,
    *projects.TOOLS,
]

__all__ = [
    "topology",
    "projects",
    "slices",
    "ALL_TOOLS",
]
