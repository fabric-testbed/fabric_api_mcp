"""
Slice inspection tools for FABRIC MCP Server.

Provides tools for listing nodes, networks, and interfaces within a slice
using fablib's list_nodes, list_networks, and list_interfaces.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastmcp.server.dependencies import get_http_headers

from fabric_api_mcp.auth.token import extract_bearer_token
from fabric_api_mcp.config import config
from fabric_api_mcp.dependencies.fablib_factory import create_fablib_manager
from fabric_api_mcp.log_helper.decorators import tool_logger
from fabric_api_mcp.utils.async_helpers import call_threadsafe

logger = logging.getLogger(__name__)


def _list_nodes(
    slice_name: Optional[str] = None,
    id_token: Optional[str] = None,
    slice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all nodes in a slice. Runs synchronously via call_threadsafe.
    """
    fablib = create_fablib_manager(id_token)

    logger.info(f"Getting slice: name={slice_name}, id={slice_id}")
    slice_obj = fablib.get_slice(name=slice_name, slice_id=slice_id)

    if slice_obj is None:
        raise ValueError(f"Slice not found: name={slice_name}, id={slice_id}")

    table = []
    for node in slice_obj.get_nodes():
        row = node.toDict()
        # In server mode, fablib doesn't have local SSH config so replace
        # the ssh_command with a generic recommendation template.
        if not config.local_mode and row.get("management_ip"):
            username = row.get("username", "ubuntu")
            mgmt_ip = row.get("management_ip", "")
            row["ssh_command"] = (
                f"ssh -i /path/to/slice_key -F /path/to/ssh_config "
                f"{username}@{mgmt_ip}"
            )
        table.append(row)

    table = sorted(table, key=lambda x: x.get("name", ""))

    return {
        "slice_name": slice_obj.get_name(),
        "slice_id": slice_obj.get_slice_id(),
        "nodes": table,
        "count": len(table),
    }


def _list_networks(
    slice_name: Optional[str] = None,
    id_token: Optional[str] = None,
    slice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all networks in a slice. Runs synchronously via call_threadsafe.
    """
    fablib = create_fablib_manager(id_token)

    logger.info(f"Getting slice: name={slice_name}, id={slice_id}")
    slice_obj = fablib.get_slice(name=slice_name, slice_id=slice_id)

    if slice_obj is None:
        raise ValueError(f"Slice not found: name={slice_name}, id={slice_id}")

    table = []
    for network in slice_obj.get_networks():
        table.append(network.toDict())

    table = sorted(table, key=lambda x: x.get("name", ""))

    return {
        "slice_name": slice_obj.get_name(),
        "slice_id": slice_obj.get_slice_id(),
        "networks": table,
        "count": len(table),
    }


def _list_interfaces(
    slice_name: Optional[str] = None,
    id_token: Optional[str] = None,
    slice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all interfaces in a slice. Runs synchronously via call_threadsafe.
    """
    fablib = create_fablib_manager(id_token)

    logger.info(f"Getting slice: name={slice_name}, id={slice_id}")
    slice_obj = fablib.get_slice(name=slice_name, slice_id=slice_id)

    if slice_obj is None:
        raise ValueError(f"Slice not found: name={slice_name}, id={slice_id}")

    table = []
    for iface in slice_obj.get_interfaces():
        table.append(iface.toDict())

    table = sorted(table, key=lambda x: (x.get("node", ""), x.get("name", "")))

    return {
        "slice_name": slice_obj.get_name(),
        "slice_id": slice_obj.get_slice_id(),
        "interfaces": table,
        "count": len(table),
    }


@tool_logger("fabric_list_nodes")
async def list_nodes(
    slice_name: Optional[str] = None,
    slice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all nodes in a FABRIC slice with their attributes.

    Returns node details including name, site, cores, RAM, disk, image,
    management IP, state, and SSH command.

    Node Record Fields:
        - id (str): Reservation ID
        - name (str): Node name
        - cores (str): Number of CPU cores
        - ram (str): RAM in GB
        - disk (str): Disk in GB
        - image (str): OS image name
        - image_type (str): Image type
        - host (str): Physical host
        - site (str): Site name
        - username (str): Login username
        - management_ip (str): Management IP address (IPv6, available when Active)
        - state (str): Reservation state (e.g., Active, Ticketed)
        - error (str): Error message if any
        - ssh_command (str): SSH command to connect (when Active).
            In local mode this is the real command from fabric_rc config.
            In server mode this is a template with placeholder paths.

    Args:
        slice_name: Name of the slice (provide either slice_name or slice_id).
        slice_id: UUID of the slice (provide either slice_name or slice_id).

    Returns:
        Dict with slice_name, slice_id, count, and nodes list.
    """
    headers = get_http_headers(include={"authorization"}) or {}
    id_token = extract_bearer_token(headers)

    if not slice_name and not slice_id:
        raise ValueError("Either slice_name or slice_id must be provided")

    return await call_threadsafe(
        _list_nodes,
        id_token=id_token,
        slice_name=slice_name,
        slice_id=slice_id,
    )


@tool_logger("fabric_list_networks")
async def list_networks(
    slice_name: Optional[str] = None,
    slice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all networks in a FABRIC slice with their attributes.

    Returns network details including name, type, layer, site, subnet,
    gateway, and state.

    Network Record Fields:
        - id (str): Reservation ID
        - name (str): Network name
        - layer (str): Network layer (e.g., L2, L3)
        - type (str): Network type (e.g., L2PTP, FABNetv4, FABNetv4Ext)
        - site (str): Site name
        - subnet (str): Network subnet (CIDR)
        - gateway (str): Gateway IP
        - state (str): Reservation state (e.g., Active, Ticketed)
        - error (str): Error message if any

    Args:
        slice_name: Name of the slice (provide either slice_name or slice_id).
        slice_id: UUID of the slice (provide either slice_name or slice_id).

    Returns:
        Dict with slice_name, slice_id, count, and networks list.
    """
    headers = get_http_headers(include={"authorization"}) or {}
    id_token = extract_bearer_token(headers)

    if not slice_name and not slice_id:
        raise ValueError("Either slice_name or slice_id must be provided")

    return await call_threadsafe(
        _list_networks,
        id_token=id_token,
        slice_name=slice_name,
        slice_id=slice_id,
    )


@tool_logger("fabric_list_interfaces")
async def list_interfaces(
    slice_name: Optional[str] = None,
    slice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all interfaces in a FABRIC slice with their attributes.

    Returns interface details including name, node, network, bandwidth,
    VLAN, MAC address, device names, and IP address.

    Interface Record Fields:
        - name (str): Interface name
        - short_name (str): Short interface name
        - node (str): Parent node name
        - network (str): Connected network name
        - bandwidth (str): Interface bandwidth
        - mode (str): Interface mode
        - vlan (str): VLAN ID
        - mac (str): MAC address (when node is Active)
        - physical_dev (str): Physical OS interface name (when Active)
        - dev (str): Device name (when Active)
        - ip_addr (str): IP address (when Active)
        - numa (str): NUMA node (when Active)
        - switch_port (str): Switch port mapping

    Args:
        slice_name: Name of the slice (provide either slice_name or slice_id).
        slice_id: UUID of the slice (provide either slice_name or slice_id).

    Returns:
        Dict with slice_name, slice_id, count, and interfaces list.
    """
    headers = get_http_headers(include={"authorization"}) or {}
    id_token = extract_bearer_token(headers)

    if not slice_name and not slice_id:
        raise ValueError("Either slice_name or slice_id must be provided")

    return await call_threadsafe(
        _list_interfaces,
        id_token=id_token,
        slice_name=slice_name,
        slice_id=slice_id,
    )


TOOLS = [list_nodes, list_networks, list_interfaces]
