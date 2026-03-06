"""
Slice lifecycle tools for FABRIC MCP Server.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

from mcp.server.fastmcp import Context

from fabric_api_mcp.config import config
from fabric_api_mcp.dependencies.fablib_factory import create_fablib_manager
from fabric_api_mcp.dependencies.fabric_manager import get_fabric_manager
from fabric_api_mcp.log_helper.decorators import tool_logger
from fabric_api_mcp.utils.async_helpers import call_threadsafe

logger = logging.getLogger(__name__)


@tool_logger("fabric_renew_slice")
async def renew_slice(
    slice_id: str,
    lease_end_time: str,
) -> Dict[str, Any]:
    """
    Renew a FABRIC slice lease.

    Args:
        slice_id: UUID of the slice to renew.
        lease_end_time: New lease end time (UTC format).
    """
    fm, id_token = get_fabric_manager()
    await call_threadsafe(
        fm.renew_slice,
        id_token=id_token,
        slice_id=slice_id,
        lease_end_time=lease_end_time,
    )
    return {"status": "ok", "slice_id": slice_id, "lease_end_time": lease_end_time}


@tool_logger("fabric_delete_slice")
async def delete_slice(
    slice_id: str,
) -> Dict[str, Any]:
    """
    Delete a FABRIC slice.

    Args:
        slice_id: UUID of the slice to delete.
    """
    fm, id_token = get_fabric_manager()
    await call_threadsafe(
        fm.delete_slice,
        id_token=id_token,
        slice_id=slice_id,
    )
    return {"status": "ok", "slice_id": slice_id}


def _get_slice(slice_name: Optional[str] = None, slice_id: Optional[str] = None):
    """Get a slice object from fablib."""
    fablib = create_fablib_manager()
    logger.info(f"Getting slice for post_boot_config: name={slice_name}, id={slice_id}")
    slice_obj = fablib.get_slice(name=slice_name, slice_id=slice_id)
    if slice_obj is None:
        raise ValueError(f"Slice not found: name={slice_name}, id={slice_id}")
    return slice_obj


def _config_single_node(slice_obj, node_name: str) -> None:
    """Configure a single node (runs synchronously in thread)."""
    node = slice_obj.get_node(name=node_name)
    if node is None:
        raise ValueError(f"Node '{node_name}' not found in slice")
    logger.info(f"Running config on node {node_name}")
    node.config()


def _post_boot_config_full(slice_obj) -> None:
    """Run post_boot_config on the entire slice (runs synchronously in thread)."""
    logger.info(f"Running post_boot_config on slice {slice_obj.get_name()}")
    slice_obj.post_boot_config()


@tool_logger("fabric_post_boot_config")
async def post_boot_config(
    slice_name: Optional[str] = None,
    slice_id: Optional[str] = None,
    node_names: Optional[Union[str, List[str]]] = None,
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Run post-boot configuration on a FABRIC slice (local mode only).

    This configures networking inside VMs after a slice reaches StableOK state.
    It must be called after a non-blocking submit (wait=False) once the slice
    is active.

    Post-boot configuration performs:
    - Configures all L3 network metadata (subnet, gateway, allocated IPs)
    - Configures VLAN interfaces
    - Sets hostnames on all nodes
    - Configures IP addresses on dataplane interfaces based on interface mode
    - Sets up routes for L3 networks
    - Runs any post-boot tasks (commands, file uploads)

    This tool requires SSH access to VMs and is only available in local mode
    where the bastion key and slice key paths are configured via fabric_rc.

    Args:
        slice_name: Name of the slice (provide either slice_name or slice_id).
        slice_id: UUID of the slice (provide either slice_name or slice_id).
        node_names: Optional list of specific node names to configure.
            If omitted, configures the entire slice (all nodes, networks,
            interfaces). If provided, only runs node.config() on the
            specified nodes. Can be a list or JSON string.
        ctx: MCP context for progress reporting (injected automatically).

    Returns:
        Dict with status and slice identifiers. If node_names was provided,
        also includes configured_nodes list.
    """
    if not config.local_mode:
        raise ValueError(
            "post_boot_config is only available in local mode. "
            "It requires SSH access to VMs which needs bastion and slice keys "
            "configured via fabric_rc."
        )

    if not slice_name and not slice_id:
        raise ValueError("Either slice_name or slice_id must be provided")

    # Normalize node_names from JSON string if needed
    if isinstance(node_names, str):
        import json
        try:
            node_names = json.loads(node_names)
        except json.JSONDecodeError:
            # Treat as single node name
            node_names = [node_names]

    timeout = config.post_boot_timeout

    try:
        # Get the slice object (in thread since it's a network call)
        slice_obj = await call_threadsafe(
            _get_slice, slice_name=slice_name, slice_id=slice_id,
        )

        if node_names:
            # Per-node configuration with progress reporting
            total = len(node_names)
            configured = []
            for i, node_name in enumerate(node_names):
                if ctx:
                    await ctx.report_progress(
                        i, total, f"Configuring node {node_name} ({i + 1}/{total})..."
                    )
                await call_threadsafe(
                    _config_single_node,
                    timeout=timeout,
                    slice_obj=slice_obj,
                    node_name=node_name,
                )
                configured.append(node_name)
                if ctx:
                    await ctx.report_progress(
                        i + 1, total, f"Configured node {node_name} ({i + 1}/{total})"
                    )

            return {
                "status": "ok",
                "slice_name": slice_obj.get_name(),
                "slice_id": slice_obj.get_slice_id(),
                "configured_nodes": configured,
            }

        # Full slice configuration
        if ctx:
            await ctx.report_progress(
                0, 1, "Running post_boot_config on entire slice..."
            )
        await call_threadsafe(
            _post_boot_config_full,
            timeout=timeout,
            slice_obj=slice_obj,
        )
        if ctx:
            await ctx.report_progress(1, 1, "Post-boot configuration complete")

        return {
            "status": "ok",
            "slice_name": slice_obj.get_name(),
            "slice_id": slice_obj.get_slice_id(),
        }

    except asyncio.TimeoutError:
        raise TimeoutError(
            f"post_boot_config timed out after {timeout} seconds. "
            f"Increase POST_BOOT_TIMEOUT env var (current: {timeout}s) or "
            f"configure specific nodes with node_names to reduce scope."
        )


TOOLS = [renew_slice, delete_slice, post_boot_config]
