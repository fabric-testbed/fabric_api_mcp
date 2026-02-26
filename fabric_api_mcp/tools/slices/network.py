"""
Network tools for FABRIC MCP Server.

Provides tools for managing FABNetv4Ext/FABNetv6Ext public IP routing.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from fastmcp.server.dependencies import get_http_headers

from fabric_api_mcp.auth.token import extract_bearer_token
from fabric_api_mcp.dependencies.fablib_factory import create_fablib_manager
from fabric_api_mcp.log_helper.decorators import tool_logger
from fabric_api_mcp.utils.async_helpers import call_threadsafe

logger = logging.getLogger(__name__)


def _make_ip_publicly_routable(
    slice_name: Optional[str] = None,
    id_token: Optional[str] = None,
    slice_id: Optional[str] = None,
    network_name: Optional[str] = None,
    ipv4: Optional[List[str]] = None,
    ipv6: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Make IPs publicly routable on a FABNetv4Ext/FABNetv6Ext network.

    This function runs synchronously and should be called via call_threadsafe.
    """
    fablib = create_fablib_manager(id_token)

    # Get the slice
    logger.info(f"Getting slice: name={slice_name}, id={slice_id}")
    slice_obj = fablib.get_slice(name=slice_name, slice_id=slice_id)

    if slice_obj is None:
        raise ValueError(f"Slice not found: name={slice_name}, id={slice_id}")

    # Get the network
    logger.info(f"Getting network: {network_name}")
    network = slice_obj.get_network(name=network_name)

    if network is None:
        raise ValueError(f"Network '{network_name}' not found in slice")

    # Get network type
    net_type = network.get_type()
    if net_type:
        net_type = str(net_type)
    logger.info(f"Network type: {net_type}")

    # Validate network type is FABNetv*Ext
    if net_type not in ["FABNetv4Ext", "FABNetv6Ext"]:
        raise ValueError(
            f"Network '{network_name}' is type '{net_type}'. "
            "Only FABNetv4Ext and FABNetv6Ext networks support public IP routing."
        )

    # Get available IPs if none specified
    available_ips = network.get_available_ips()
    logger.info(f"Available IPs: {available_ips[:5] if available_ips else None}...")

    # Determine which IPs to make public
    if net_type == "FABNetv4Ext":
        if not ipv4:
            # Use first available IP if not specified
            if available_ips:
                ipv4 = [str(available_ips[0])]
            else:
                raise ValueError("No available IPs and no ipv4 addresses specified")
        logger.info(f"Making IPv4 addresses publicly routable: {ipv4}")
        network.make_ip_publicly_routable(ipv4=ipv4)
    else:  # FABNetv6Ext
        if not ipv6:
            # Use first available IP if not specified
            if available_ips:
                ipv6 = [str(available_ips[0])]
            else:
                raise ValueError("No available IPs and no ipv6 addresses specified")
        logger.info(f"Making IPv6 addresses publicly routable: {ipv6}")
        network.make_ip_publicly_routable(ipv6=ipv6)

    # Submit the slice to apply changes
    logger.info("Submitting slice to apply public IP routing changes")
    slice_obj.submit(wait=False)

    # Get the public IPs after submit
    public_ips = network.get_public_ips()

    return {
        "status": "submitted",
        "slice_name": slice_obj.get_name(),
        "slice_id": slice_obj.get_slice_id(),
        "network_name": network_name,
        "network_type": net_type,
        "public_ips": [str(ip) for ip in public_ips] if public_ips else [],
        "gateway": str(network.get_gateway()) if network.get_gateway() else None,
        "subnet": str(network.get_subnet()) if network.get_subnet() else None,
    }


def _get_network_info(
    slice_name: Optional[str] = None,
    id_token: Optional[str] = None,
    slice_id: Optional[str] = None,
    network_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get network information including available and public IPs.

    This function runs synchronously and should be called via call_threadsafe.
    """
    fablib = create_fablib_manager(id_token)

    # Get the slice
    logger.info(f"Getting slice: name={slice_name}, id={slice_id}")
    slice_obj = fablib.get_slice(name=slice_name, slice_id=slice_id)

    if slice_obj is None:
        raise ValueError(f"Slice not found: name={slice_name}, id={slice_id}")

    # Get the network
    logger.info(f"Getting network: {network_name}")
    network = slice_obj.get_network(name=network_name)

    if network is None:
        raise ValueError(f"Network '{network_name}' not found in slice")

    # Get network details
    net_type = network.get_type()
    available_ips = network.get_available_ips()
    public_ips = network.get_public_ips()

    return {
        "slice_name": slice_obj.get_name(),
        "slice_id": slice_obj.get_slice_id(),
        "network_name": network_name,
        "network_type": net_type,
        "gateway": str(network.get_gateway()) if network.get_gateway() else None,
        "subnet": str(network.get_subnet()) if network.get_subnet() else None,
        "available_ips": [str(ip) for ip in available_ips[:10]] if available_ips else [],
        "available_ips_count": len(available_ips) if available_ips else 0,
        "public_ips": [str(ip) for ip in public_ips] if public_ips else [],
    }


@tool_logger("fabric_make_ip_routable")
async def make_ip_publicly_routable(
    network_name: str,
    slice_name: Optional[str] = None,
    slice_id: Optional[str] = None,
    ipv4: Optional[Union[str, List[str]]] = None,
    ipv6: Optional[Union[str, List[str]]] = None,
) -> Dict[str, Any]:
    """
    Make IP addresses publicly routable on a FABNetv4Ext or FABNetv6Ext network.

    After a slice with FABNetv4Ext/FABNetv6Ext networks is provisioned, users must
    explicitly request public IP routing for external access. This tool enables
    that by calling make_ip_publicly_routable on the network and submitting the slice.

    Args:
        network_name: Name of the FABNetv4Ext or FABNetv6Ext network.

        slice_name: Name of the slice (provide either slice_name or slice_id).

        slice_id: UUID of the slice (provide either slice_name or slice_id).

        ipv4: IPv4 address(es) to make publicly routable (for FABNetv4Ext).
            Can be a single IP string or list of IPs.
            If omitted, uses the first available IP from the network.

        ipv6: IPv6 address(es) to make publicly routable (for FABNetv6Ext).
            Can be a single IP string or list of IPs.
            If omitted, uses the first available IP from the network.

    Returns:
        Dict with status and assigned public IPs:
        - status: "submitted"
        - slice_name, slice_id: Slice identifiers
        - network_name, network_type: Network details
        - public_ips: List of publicly routable IPs
        - gateway: Network gateway IP
        - subnet: Network subnet

    Note:
        - Only works with FABNetv4Ext and FABNetv6Ext network types.
        - This submits a slice modification (wait=False). Wait for the slice to
          reach **ModifyOK** state, then call ``fabric_get_network_info`` to
          re-fetch the actual assigned public IPs — the orchestrator may change
          the requested IP (especially for FABNetv4Ext where the subnet is shared).

    IPv4Ext vs IPv6Ext behavior:
        - **FABNetv4Ext**: The IPv4 subnet is SHARED across all slices at a site.
          Due to limited IPv4 address space, requested IPs may already be in use.
          If the requested IP is unavailable, the orchestrator returns the next
          available IP. Always re-fetch via ``fabric_get_network_info`` after
          ModifyOK and configure the **returned** IP inside your VM.

        - **FABNetv6Ext**: The entire IPv6 subnet is allocated to YOUR slice.
          Any IP from the subnet can be requested and made public. You have
          full control over the entire subnet.
    """
    # Extract bearer token from request
    headers = get_http_headers(include={"authorization"}) or {}
    id_token = extract_bearer_token(headers)

    if not slice_name and not slice_id:
        raise ValueError("Either slice_name or slice_id must be provided")

    # Normalize ipv4/ipv6 to lists
    if isinstance(ipv4, str):
        ipv4 = [ipv4]
    if isinstance(ipv6, str):
        ipv6 = [ipv6]

    result = await call_threadsafe(
        _make_ip_publicly_routable,
        id_token=id_token,
        slice_name=slice_name,
        slice_id=slice_id,
        network_name=network_name,
        ipv4=ipv4,
        ipv6=ipv6,
    )

    return result


@tool_logger("fabric_get_network_info")
async def get_network_info(
    network_name: str,
    slice_name: Optional[str] = None,
    slice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get detailed information about a network in a slice.

    Useful for checking available IPs before making them publicly routable,
    or for getting the gateway and subnet information for manual IP configuration.
    Also call this **after** ``fabric_make_ip_routable`` once the slice reaches
    ModifyOK — the orchestrator may assign a different IP than requested
    (especially for FABNetv4Ext). Always use the returned ``public_ips``.

    Args:
        network_name: Name of the network.

        slice_name: Name of the slice (provide either slice_name or slice_id).

        slice_id: UUID of the slice (provide either slice_name or slice_id).

    Returns:
        Dict with network details:
        - slice_name, slice_id: Slice identifiers
        - network_name, network_type: Network identifiers
        - gateway: Network gateway IP
        - subnet: Network subnet (CIDR)
        - available_ips: First 10 available IPs (use for make-ip-publicly-routable)
        - available_ips_count: Total count of available IPs
        - public_ips: List of IPs already marked as publicly routable
    """
    # Extract bearer token from request
    headers = get_http_headers(include={"authorization"}) or {}
    id_token = extract_bearer_token(headers)

    if not slice_name and not slice_id:
        raise ValueError("Either slice_name or slice_id must be provided")

    result = await call_threadsafe(
        _get_network_info,
        id_token=id_token,
        slice_name=slice_name,
        slice_id=slice_id,
        network_name=network_name,
    )

    return result


TOOLS = [make_ip_publicly_routable, get_network_info]
