"""
Dependency injection for FABRIC MCP Server.
"""
from server.dependencies.fabric_manager import FabricManagerFactory, fabric_manager_factory, \
    get_fabric_manager

__all__ = [
    "FabricManagerFactory",
    "fabric_manager_factory",
    "get_fabric_manager",
]
