"""
High-level slice modification tool for FABRIC MCP Server.

Provides a declarative interface to add or remove nodes, components, and networks
from existing slices using FablibManager from fabrictestbed-extensions.
"""
from __future__ import annotations

import logging
from ipaddress import IPv4Network
from typing import Any, Dict, List, Optional, Union

from fabrictestbed_extensions.fablib.fablib_v2 import FablibManagerV2
from fastmcp.server.dependencies import get_http_headers

from server.auth.token import extract_bearer_token
from server.config import config
from server.log_helper.decorators import tool_logger
from server.utils.async_helpers import call_threadsafe

# Import constants and helpers from builder
from server.tools.slices.builder import (
    VALID_COMPONENT_MODELS,
    VALID_L2_NETWORK_TYPES,
    VALID_L3_NETWORK_TYPES,
    VALID_NETWORK_TYPES,
    VALID_NIC_MODELS,
    L3_TYPE_MAP,
    SMARTNIC_MODELS,
    DEFAULT_SMARTNIC,
    _determine_network_type,
    _select_nic_for_network,
    _get_or_create_interface,
)

logger = logging.getLogger(__name__)


def _get_fablib_manager(id_token: str) -> FablibManagerV2:
    """Create a FablibManager instance with the given id_token."""
    return FablibManagerV2(
        id_token=id_token,
        credmgr_host=config.credmgr_host,
        orchestrator_host=config.orchestrator_host,
        core_api_host=config.core_api_host,
        am_host=config.am_host,
        auto_token_refresh=False,
        validate_config=False,
        log_level=config.log_level,
        log_path=True
    )


def _modify_slice_resources(
    id_token: str,
    slice_name: Optional[str] = None,
    slice_id: Optional[str] = None,
    # Add operations
    add_nodes: Optional[List[Dict[str, Any]]] = None,
    add_components: Optional[List[Dict[str, Any]]] = None,
    add_networks: Optional[List[Dict[str, Any]]] = None,
    # Remove operations
    remove_nodes: Optional[List[str]] = None,
    remove_components: Optional[List[Dict[str, str]]] = None,
    remove_networks: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Add or remove nodes, components, and/or networks from an existing slice.

    This function runs synchronously and should be called via call_threadsafe.
    """
    fablib = _get_fablib_manager(id_token)

    # Get the existing slice - IMPORTANT: always get latest before modifications
    logger.info(f"Getting slice: name={slice_name}, id={slice_id}")
    slice_obj = fablib.get_slice(name=slice_name, slice_id=slice_id)

    if slice_obj is None:
        raise ValueError(f"Slice not found: name={slice_name}, id={slice_id}")

    slice_name = slice_obj.get_name()
    slice_id_str = slice_obj.get_slice_id()
    logger.info(f"Modifying slice: {slice_name} ({slice_id_str})")

    # Track all nodes (existing + new) for network connections
    node_map: Dict[str, Any] = {}

    # Load existing nodes into node_map
    for existing_node in slice_obj.get_nodes():
        node_map[existing_node.get_name()] = existing_node
        logger.info(f"Found existing node: {existing_node.get_name()}")

    # Track results
    added_nodes = []
    added_components = []
    added_networks = []
    removed_nodes = []
    removed_components = []
    removed_networks = []

    # === REMOVE OPERATIONS (do these first) ===

    # Remove networks first (before removing nodes that may be connected)
    if remove_networks:
        for net_name in remove_networks:
            try:
                network = slice_obj.get_network(name=net_name)
                if network:
                    logger.info(f"Removing network: {net_name}")
                    network.delete()
                    removed_networks.append(net_name)
                else:
                    logger.warning(f"Network not found: {net_name}")
            except Exception as e:
                logger.warning(f"Failed to remove network {net_name}: {e}")

    # Remove components from nodes
    if remove_components:
        for comp_spec in remove_components:
            node_name = comp_spec.get("node")
            comp_name = comp_spec.get("name") or comp_spec.get("component")

            if not node_name or not comp_name:
                raise ValueError("remove_components entries must have 'node' and 'name' fields")

            if node_name not in node_map:
                logger.warning(f"Node not found for component removal: {node_name}")
                continue

            try:
                node = node_map[node_name]
                component = node.get_component(name=comp_name)
                if component:
                    logger.info(f"Removing component {comp_name} from node {node_name}")
                    component.delete()
                    removed_components.append({"node": node_name, "component": comp_name})
                else:
                    logger.warning(f"Component not found: {comp_name} on node {node_name}")
            except Exception as e:
                logger.warning(f"Failed to remove component {comp_name} from {node_name}: {e}")

    # Remove nodes
    if remove_nodes:
        for node_name in remove_nodes:
            if node_name not in node_map:
                logger.warning(f"Node not found for removal: {node_name}")
                continue

            try:
                node = node_map[node_name]
                logger.info(f"Removing node: {node_name}")
                node.delete()
                del node_map[node_name]
                removed_nodes.append(node_name)
            except Exception as e:
                logger.warning(f"Failed to remove node {node_name}: {e}")

    # === ADD OPERATIONS ===

    # Add new nodes
    if add_nodes:
        for node_spec in add_nodes:
            node_name = node_spec["name"]

            if node_name in node_map:
                raise ValueError(f"Node '{node_name}' already exists in slice")

            site = node_spec.get("site")
            cores = node_spec.get("cores", 2)
            ram = node_spec.get("ram", 8)
            disk = node_spec.get("disk", 10)
            image = node_spec.get("image", "default_rocky_8")

            # Auto-select random site if not specified
            if not site:
                def site_filter(s):
                    return (
                        s.get("cores_available", 0) >= cores
                        and s.get("ram_available", 0) >= ram
                        and s.get("disk_available", 0) >= disk
                    )
                site = fablib.get_random_site(filter_function=site_filter)
                logger.info(f"Auto-selected site '{site}' for node {node_name}")

            logger.info(f"Adding node {node_name} at site {site}")
            node = slice_obj.add_node(
                name=node_name,
                site=site,
                cores=cores,
                ram=ram,
                disk=disk,
                image=image,
            )
            node_map[node_name] = node
            added_nodes.append(node_name)

            # Add components specified with the node
            node_components = node_spec.get("components", [])
            for i, comp_spec in enumerate(node_components):
                model = comp_spec.get("model")
                comp_name = comp_spec.get("name", f"{node_name}-{model}-{i}")

                if model not in VALID_COMPONENT_MODELS:
                    raise ValueError(f"Unknown component model: {model}")

                logger.info(f"Adding component {comp_name} ({model}) to node {node_name}")
                node.add_component(model=model, name=comp_name)
                added_components.append({"node": node_name, "component": comp_name, "model": model})

    # Add components to existing nodes
    if add_components:
        for comp_spec in add_components:
            node_name = comp_spec.get("node")
            model = comp_spec.get("model")
            comp_name = comp_spec.get("name")

            if not node_name:
                raise ValueError("Component spec must include 'node' field")
            if not model:
                raise ValueError("Component spec must include 'model' field")

            if node_name not in node_map:
                raise ValueError(f"Node '{node_name}' not found in slice")

            if model not in VALID_COMPONENT_MODELS:
                raise ValueError(f"Unknown component model: {model}")

            node = node_map[node_name]
            if not comp_name:
                comp_name = f"{node_name}-{model}-new"

            logger.info(f"Adding component {comp_name} ({model}) to existing node {node_name}")
            node.add_component(model=model, name=comp_name)
            added_components.append({"node": node_name, "component": comp_name, "model": model})

    # Track NICs for reuse
    node_nics: Dict[str, Dict[str, Any]] = {name: {} for name in node_map}

    # Add networks
    if add_networks:
        for net_spec in add_networks:
            net_name = net_spec["name"]
            requested_type = net_spec.get("type")
            bandwidth = net_spec.get("bandwidth")
            user_nic_model = net_spec.get("nic") or net_spec.get("nic_model")
            subnet = net_spec.get("subnet")

            # Support both simple "nodes" and detailed "interfaces" format
            connected_nodes = net_spec.get("nodes", [])
            interface_specs = net_spec.get("interfaces", [])

            if connected_nodes and not interface_specs:
                interface_specs = [{"node": n} for n in connected_nodes]
            elif interface_specs:
                connected_nodes = [ispec.get("node") for ispec in interface_specs]

            if len(interface_specs) < 2:
                raise ValueError(
                    f"Network {net_name} must connect at least 2 nodes/interfaces"
                )

            # Validate all referenced nodes exist
            for node_name in connected_nodes:
                if node_name not in node_map:
                    raise ValueError(f"Network {net_name} references unknown node: {node_name}")

            # Collect sites
            net_sites = {node_map[n].get_site() for n in connected_nodes}

            # Resolve network type
            net_type = _determine_network_type(requested_type, net_sites)

            logger.info(
                f"Adding network {net_name} (type={net_type}) connecting nodes: {connected_nodes}"
            )

            # Select NIC model
            if user_nic_model:
                if user_nic_model not in VALID_NIC_MODELS:
                    raise ValueError(f"Invalid NIC model: {user_nic_model}")
                nic_model = user_nic_model
            else:
                nic_model = _select_nic_for_network(net_type, bandwidth)

            # Check for FABNet* multi-site handling
            fabnet_types = ["FABNetv4", "FABNetv6", "FABNetv4Ext", "FABNetv6Ext"]
            is_fabnet = net_type in fabnet_types

            if is_fabnet and len(net_sites) > 1:
                # Group interface specs by site
                specs_by_site: Dict[str, List[Dict[str, Any]]] = {}
                for ispec in interface_specs:
                    node_name = ispec.get("node")
                    node_site = node_map[node_name].get_site()
                    if node_site not in specs_by_site:
                        specs_by_site[node_site] = []
                    specs_by_site[node_site].append(ispec)

                l3_type = L3_TYPE_MAP[net_type]
                for site, site_specs in specs_by_site.items():
                    site_net_name = f"{net_name}-{site}"
                    site_interfaces = []

                    for ispec in site_specs:
                        node_name = ispec.get("node")
                        node = node_map[node_name]
                        iface = _get_or_create_interface(
                            node, node_nics, ispec, net_name, nic_model
                        )
                        iface.set_mode('auto')
                        site_interfaces.append(iface)

                    logger.info(f"Creating per-site {net_type} network {site_net_name} at {site}")
                    slice_obj.add_l3network(
                        name=site_net_name,
                        interfaces=site_interfaces,
                        type=l3_type,
                    )
                    added_networks.append(site_net_name)
                continue

            # Add NIC interfaces for each interface spec
            interfaces = []
            for ispec in interface_specs:
                node_name = ispec.get("node")
                node = node_map[node_name]
                iface = _get_or_create_interface(
                    node, node_nics, ispec, net_name, nic_model
                )
                iface.set_mode('auto')
                interfaces.append(iface)

            # Create network
            if net_type in VALID_L3_NETWORK_TYPES:
                l3_type = L3_TYPE_MAP[net_type]
                logger.info(f"Creating L3 network {net_name} of type {l3_type}")
                slice_obj.add_l3network(name=net_name, interfaces=interfaces, type=l3_type)
            else:
                # L2 network
                logger.info(f"Creating L2 network {net_name} (type={net_type})")
                if subnet:
                    subnet_obj = IPv4Network(subnet)
                    net_service = slice_obj.add_l2network(
                        name=net_name,
                        interfaces=interfaces,
                        type=net_type,
                        subnet=subnet_obj,
                    )
                else:
                    net_service = slice_obj.add_l2network(
                        name=net_name,
                        interfaces=interfaces,
                        type=net_type,
                    )

                if bandwidth and net_type == "L2PTP":
                    logger.info(f"Setting bandwidth to {bandwidth} Gbps")
                    net_service.set_bandwidth(bw=bandwidth)

            added_networks.append(net_name)

    # Submit the modifications (non-blocking)
    logger.info("Submitting slice modifications (wait=False)")
    slice_obj.submit(wait=False)

    return {
        "status": "submitted",
        "slice_name": slice_name,
        "slice_id": slice_id_str,
        "added": {
            "nodes": added_nodes,
            "components": added_components,
            "networks": added_networks,
        },
        "removed": {
            "nodes": removed_nodes,
            "components": removed_components,
            "networks": removed_networks,
        },
    }


@tool_logger("modify-slice-resources")
async def modify_slice_resources(
    slice_name: Optional[str] = None,
    slice_id: Optional[str] = None,
    # Add operations
    add_nodes: Optional[List[Dict[str, Any]]] = None,
    add_components: Optional[List[Dict[str, Any]]] = None,
    add_networks: Optional[List[Dict[str, Any]]] = None,
    # Remove operations
    remove_nodes: Optional[List[str]] = None,
    remove_components: Optional[List[Dict[str, str]]] = None,
    remove_networks: Optional[List[str]] = None,
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add or remove nodes, components, and/or networks from an existing slice.

    This tool fetches the latest slice topology, applies the requested modifications,
    and submits the changes. Always retrieves the current slice state before
    making changes to avoid conflicts. Submits with wait=False for non-blocking.

    Args:
        slice_name: Name of the slice to modify (provide either slice_name or slice_id).

        slice_id: UUID of the slice to modify (provide either slice_name or slice_id).

        add_nodes: List of new nodes to add. Each node is a dict with:
            - name (str, required): Unique node name
            - site (str, optional): FABRIC site. Auto-selected if omitted.
            - cores (int, optional): CPU cores (default: 2)
            - ram (int, optional): RAM in GB (default: 8)
            - disk (int, optional): Disk in GB (default: 10)
            - image (str, optional): OS image (default: "default_rocky_8")
            - components (list, optional): Components to add to this node

        add_components: List of components to add to EXISTING nodes. Each is a dict with:
            - node (str, required): Name of existing node to add component to
            - model (str, required): Component model (GPU_TeslaT4, NIC_ConnectX_6, etc.)
            - name (str, optional): Component name

        add_networks: List of networks to add. Each is a dict with:
            - name (str, required): Network name
            - nodes (list): Simple form - node names to connect (auto-creates NICs)
            - interfaces (list): Detailed form for SmartNIC port control:
                - node (str): Node name
                - nic (str, optional): NIC name (reuse existing or create named)
                - port (int, optional): Port index (0 or 1 for SmartNICs)
                - nic_model (str, optional): NIC model for this interface
            - type (str, optional): Network type (L2PTP, L2Bridge, FABNetv4, etc.)
            - bandwidth (int, optional): Bandwidth in Gbps (L2PTP only)
            - nic (str, optional): Default NIC model override
            - subnet (str, optional): IPv4 subnet for L2 networks (e.g., "192.168.1.0/24")

        remove_nodes: List of node names to remove from the slice.

        remove_components: List of components to remove. Each is a dict with:
            - node (str, required): Node name containing the component
            - name (str, required): Component name to remove

        remove_networks: List of network names to remove from the slice.

    Returns:
        Dict with modification results:
        - status: "submitted"
        - slice_name, slice_id: Slice identifiers
        - added: {nodes: [...], components: [...], networks: [...]}
        - removed: {nodes: [...], components: [...], networks: [...]}

    Example - Add a new node with GPU:
        modify-slice-resources(
            slice_name="my-slice",
            add_nodes=[{
                "name": "node3",
                "site": "UTAH",
                "cores": 16,
                "components": [{"model": "GPU_TeslaT4"}]
            }]
        )

    Example - Remove a node and its connected network:
        modify-slice-resources(
            slice_name="my-slice",
            remove_networks=["net1"],
            remove_nodes=["node2"]
        )

    Example - Add NIC to existing node and remove old component:
        modify-slice-resources(
            slice_name="my-slice",
            add_components=[{"node": "node1", "model": "NIC_ConnectX_6"}],
            remove_components=[{"node": "node1", "name": "old-nic"}]
        )

    Example - Add network connecting existing nodes:
        modify-slice-resources(
            slice_name="my-slice",
            add_networks=[{
                "name": "internal-net",
                "nodes": ["node1", "node2"],
                "subnet": "192.168.2.0/24"
            }]
        )

    Note:
        - Remove operations are performed BEFORE add operations
        - Remove networks before removing nodes that are connected to them
        - The slice is submitted with wait=False (non-blocking)
        - Use query-slices to check slice state after modification
    """
    headers = get_http_headers() or {}
    id_token = extract_bearer_token(headers)

    if not slice_name and not slice_id:
        raise ValueError("Either slice_name or slice_id must be provided")

    has_add = add_nodes or add_components or add_networks
    has_remove = remove_nodes or remove_components or remove_networks

    if not has_add and not has_remove:
        raise ValueError(
            "At least one of add_nodes, add_components, add_networks, "
            "remove_nodes, remove_components, or remove_networks must be provided"
        )

    result = await call_threadsafe(
        _modify_slice_resources,
        id_token=id_token,
        slice_name=slice_name,
        slice_id=slice_id,
        add_nodes=add_nodes,
        add_components=add_components,
        add_networks=add_networks,
        remove_nodes=remove_nodes,
        remove_components=remove_components,
        remove_networks=remove_networks,
    )

    return result


# Keep backward compatibility alias
add_to_slice = modify_slice_resources

TOOLS = [modify_slice_resources]
