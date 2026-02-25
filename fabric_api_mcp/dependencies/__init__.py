"""
Dependency injection for FABRIC MCP Server.
"""
from fabric_api_mcp.dependencies.fabric_manager import FabricManagerFactory, fabric_manager_factory, \
    get_fabric_manager
from fabric_api_mcp.dependencies.fablib_factory import create_fablib_manager

__all__ = [
    "FabricManagerFactory",
    "fabric_manager_factory",
    "get_fabric_manager",
    "create_fablib_manager",
]
