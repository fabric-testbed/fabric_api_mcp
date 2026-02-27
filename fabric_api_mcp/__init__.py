"""FABRIC MCP Server — exposes FABRIC API operations as LLM-accessible tools."""
from importlib.metadata import version

__all__ = ["__version__"]

# Version gets picked up from package metadata in pyproject.toml.
__version__ = version(__name__)
