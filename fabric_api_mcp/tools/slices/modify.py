"""
Slice modification tools for FABRIC MCP Server.
"""
from __future__ import annotations

import logging
from ipaddress import IPv4Network
from typing import Any, Dict, List, Optional, Union

from fastmcp.server.dependencies import get_http_headers

from fabric_api_mcp.auth.token import extract_bearer_token
from fabric_api_mcp.config import config
from fabric_api_mcp.dependencies.fabric_manager import get_fabric_manager
from fabric_api_mcp.dependencies.fablib_factory import create_fablib_manager
from fabric_api_mcp.log_helper.decorators import tool_logger
from fabric_api_mcp.utils.async_helpers import call_threadsafe

# Import constants and helpers from create module
from fabric_api_mcp.tools.slices.create import (
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
    _resolve_interface,
    _get_available_sites,
    _select_site_for_node,
)

logger = logging.getLogger(__name__)


def _modify_slice_resources(
    slice_name: Optional[str] = None,
    id_token: Optional[str] = None,
    slice_id: Optional[str] = None,
    # Add operations
    add_nodes: Optional[List[Dict[str, Any]]] = None,
    add_components: Optional[List[Dict[str, Any]]] = None,
    add_switches: Optional[List[Dict[str, Any]]] = None,
    add_facility_ports: Optional[List[Dict[str, Any]]] = None,
    add_networks: Optional[List[Dict[str, Any]]] = None,
    add_port_mirrors: Optional[List[Dict[str, Any]]] = None,
    # Remove operations
    remove_port_mirrors: Optional[List[str]] = None,
    remove_networks: Optional[List[str]] = None,
    remove_facility_ports: Optional[List[str]] = None,
    remove_switches: Optional[List[str]] = None,
    remove_components: Optional[List[Dict[str, str]]] = None,
    remove_nodes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Add or remove nodes, components, and/or networks from an existing slice.

    This function runs synchronously and should be called via call_threadsafe.
    """
    fablib = create_fablib_manager(id_token)

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
    added_switches_list = []
    added_facility_ports_list = []
    added_networks = []
    added_port_mirrors_list = []
    removed_nodes = []
    removed_components = []
    removed_switches_list = []
    removed_facility_ports_list = []
    removed_networks = []
    removed_port_mirrors_list = []

    # Track used sites for auto-selection diversity
    used_sites: List[str] = [node.get_site() for node in slice_obj.get_nodes()]

    # Pre-fetch available sites once if any node needs auto-selection
    available_sites: List[Dict[str, Any]] = []
    if add_nodes:
        needs_auto_site = any(not node_spec.get("site") for node_spec in add_nodes)
        if needs_auto_site:
            logger.info("Pre-fetching available sites for auto-selection")
            available_sites = _get_available_sites(fablib, update=True)

    # === REMOVE OPERATIONS ===
    # Order: port_mirrors → networks → facility_ports → switches → components → nodes

    # Remove port mirrors first
    if remove_port_mirrors:
        for pm_name in remove_port_mirrors:
            try:
                pm = slice_obj.get_network(name=pm_name)
                if pm:
                    logger.info(f"Removing port mirror: {pm_name}")
                    pm.delete()
                    removed_port_mirrors_list.append(pm_name)
                else:
                    logger.warning(f"Port mirror not found: {pm_name}")
            except Exception as e:
                logger.warning(f"Failed to remove port mirror {pm_name}: {e}")

    # Remove networks (before removing nodes/switches/fps that may be connected)
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

    # Remove facility ports
    if remove_facility_ports:
        for fp_name in remove_facility_ports:
            try:
                fp = slice_obj.get_network(name=fp_name)
                if fp:
                    logger.info(f"Removing facility port: {fp_name}")
                    fp.delete()
                    removed_facility_ports_list.append(fp_name)
                else:
                    logger.warning(f"Facility port not found: {fp_name}")
            except Exception as e:
                logger.warning(f"Failed to remove facility port {fp_name}: {e}")

    # Remove switches
    if remove_switches:
        for sw_name in remove_switches:
            try:
                sw = slice_obj.get_node(name=sw_name)
                if sw:
                    logger.info(f"Removing switch: {sw_name}")
                    sw.delete()
                    removed_switches_list.append(sw_name)
                else:
                    logger.warning(f"Switch not found: {sw_name}")
            except Exception as e:
                logger.warning(f"Failed to remove switch {sw_name}: {e}")

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
    # Order: nodes → components → switches → facility_ports → networks → port_mirrors

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
                site = _select_site_for_node(available_sites, cores, ram, disk, used_sites)
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
            used_sites.append(site)  # Track for diversity in site selection

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

            # Add per-node FABNet connectivity if requested
            fabnet = node_spec.get("fabnet")
            if fabnet:
                fabnet_type = "IPv4"  # default
                if isinstance(fabnet, dict):
                    fabnet_type = fabnet.get("type", "IPv4")
                elif isinstance(fabnet, str):
                    fabnet_type = fabnet
                logger.info(f"Adding FABNet ({fabnet_type}) to node {node_name}")
                node.add_fabnet(net_type=fabnet_type)

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

    # Add P4 switches
    switches_map: Dict[str, Any] = {}
    if add_switches:
        for sw_spec in add_switches:
            sw_name = sw_spec["name"]
            sw_site = sw_spec["site"]
            logger.info(f"Adding P4 switch {sw_name} at site {sw_site}")
            switch = slice_obj.add_switch(name=sw_name, site=sw_site)
            switches_map[sw_name] = switch
            added_switches_list.append(sw_name)

    # Add facility ports
    facility_ports_map: Dict[str, Any] = {}
    if add_facility_ports:
        for fp_spec in add_facility_ports:
            fp_name = fp_spec["name"]
            fp_site = fp_spec["site"]
            fp_vlan = fp_spec["vlan"]
            logger.info(f"Adding facility port {fp_name} at site {fp_site} (VLAN {fp_vlan})")
            fp = slice_obj.add_facility_port(
                name=fp_name, site=fp_site, vlan=str(fp_vlan)
            )
            facility_ports_map[fp_name] = fp
            added_facility_ports_list.append(fp_name)

    # Track NICs for reuse
    node_nics: Dict[str, Dict[str, Any]] = {name: {} for name in node_map}

    # In local mode, default interface mode to "auto"; users can override
    # per interface via "mode" in the interface spec. Server mode: no mode set.
    set_iface_mode = config.local_mode

    # Add networks
    if add_networks:
        for net_spec in add_networks:
            net_name = net_spec["name"]
            requested_type = net_spec.get("type")
            bandwidth = net_spec.get("bandwidth")
            user_nic_model = net_spec.get("nic") or net_spec.get("nic_model")
            subnet = net_spec.get("subnet")
            ero = net_spec.get("ero")  # Explicit Route Option: list of site hops

            # Support both simple "nodes" and detailed "interfaces" format
            connected_nodes = net_spec.get("nodes", [])
            interface_specs = net_spec.get("interfaces", [])

            if connected_nodes and not interface_specs:
                interface_specs = [{"node": n} for n in connected_nodes]

            # Collect sites from all interface endpoints
            def _get_iface_site(ispec):
                if "node" in ispec:
                    if ispec["node"] not in node_map:
                        raise ValueError(f"Network {net_name} references unknown node: {ispec['node']}")
                    return node_map[ispec["node"]].get_site()
                if "switch" in ispec:
                    if ispec["switch"] not in switches_map:
                        raise ValueError(f"Network {net_name} references unknown switch: {ispec['switch']}")
                    return switches_map[ispec["switch"]].get_site()
                if "facility_port" in ispec:
                    if ispec["facility_port"] not in facility_ports_map:
                        raise ValueError(f"Network {net_name} references unknown facility port: {ispec['facility_port']}")
                    return facility_ports_map[ispec["facility_port"]].get_site()
                raise ValueError(
                    f"Interface spec for network {net_name} must have 'node', 'switch', or 'facility_port'"
                )

            net_sites = {_get_iface_site(ispec) for ispec in interface_specs}

            # Resolve network type (L2PTP only with ERO for dedicated QoS)
            net_type = _determine_network_type(requested_type, net_sites, ero=ero)

            logger.info(f"Adding network {net_name} (type={net_type})")

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
                    ispec_site = _get_iface_site(ispec)
                    if ispec_site not in specs_by_site:
                        specs_by_site[ispec_site] = []
                    specs_by_site[ispec_site].append(ispec)

                l3_type = L3_TYPE_MAP[net_type]
                for site, site_specs in specs_by_site.items():
                    site_net_name = f"{net_name}-{site}"
                    site_interfaces = []

                    for ispec in site_specs:
                        iface = _resolve_interface(
                            ispec, node_map, node_nics,
                            switches_map, facility_ports_map,
                            net_name, nic_model,
                        )
                        if set_iface_mode:
                            mode = ispec.get("mode", "auto")
                            iface.set_mode(mode)
                        site_interfaces.append(iface)

                    logger.info(f"Creating per-site {net_type} network {site_net_name} at {site}")
                    slice_obj.add_l3network(
                        name=site_net_name,
                        interfaces=site_interfaces,
                        type=l3_type,
                    )
                    added_networks.append(site_net_name)
                continue

            # Resolve interfaces for each interface spec
            interfaces = []
            for ispec in interface_specs:
                iface = _resolve_interface(
                    ispec, node_map, node_nics,
                    switches_map, facility_ports_map,
                    net_name, nic_model,
                )
                if set_iface_mode:
                    mode = ispec.get("mode", "auto")
                    iface.set_mode(mode)
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

                # ERO sets explicit route hops for L2PTP (dedicated QoS)
                if ero and net_type == "L2PTP":
                    logger.info(f"Setting ERO route hops for network {net_name}: {ero}")
                    net_service.set_l2_route_hops(hops=ero)

                # Bandwidth only applies to L2PTP (with ERO)
                if bandwidth and net_type == "L2PTP":
                    logger.info(f"Setting bandwidth to {bandwidth} Gbps")
                    net_service.set_bandwidth(bw=bandwidth)

            added_networks.append(net_name)

    # Add port mirror services (after networks)
    if add_port_mirrors:
        for pm_spec in add_port_mirrors:
            pm_name = pm_spec["name"]
            mirror_iface_name = pm_spec["mirror_interface_name"]
            receive_spec = pm_spec["receive_interface"]
            direction = pm_spec.get("mirror_direction", "both")

            logger.info(
                f"Adding port mirror {pm_name}: mirror={mirror_iface_name}, "
                f"direction={direction}"
            )

            receive_iface = _resolve_interface(
                receive_spec, node_map, node_nics,
                switches_map, facility_ports_map,
                pm_name, DEFAULT_SMARTNIC,
            )

            slice_obj.add_port_mirror_service(
                name=pm_name,
                mirror_interface_name=mirror_iface_name,
                receive_interface=receive_iface,
                mirror_direction=direction,
            )
            added_port_mirrors_list.append(pm_name)

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
            "switches": added_switches_list,
            "facility_ports": added_facility_ports_list,
            "networks": added_networks,
            "port_mirrors": added_port_mirrors_list,
        },
        "removed": {
            "nodes": removed_nodes,
            "components": removed_components,
            "switches": removed_switches_list,
            "facility_ports": removed_facility_ports_list,
            "networks": removed_networks,
            "port_mirrors": removed_port_mirrors_list,
        },
    }


@tool_logger("fabric_modify_slice")
async def modify_slice_resources(
    slice_name: Optional[str] = None,
    slice_id: Optional[str] = None,
    # Add operations
    add_nodes: Optional[List[Dict[str, Any]]] = None,
    add_components: Optional[List[Dict[str, Any]]] = None,
    add_switches: Optional[List[Dict[str, Any]]] = None,
    add_facility_ports: Optional[List[Dict[str, Any]]] = None,
    add_networks: Optional[List[Dict[str, Any]]] = None,
    add_port_mirrors: Optional[List[Dict[str, Any]]] = None,
    # Remove operations
    remove_port_mirrors: Optional[List[str]] = None,
    remove_networks: Optional[List[str]] = None,
    remove_facility_ports: Optional[List[str]] = None,
    remove_switches: Optional[List[str]] = None,
    remove_components: Optional[List[Dict[str, str]]] = None,
    remove_nodes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Add or remove nodes, components, switches, facility ports, networks,
    and/or port mirrors from an existing slice.

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
            - fabnet (bool/str/dict, optional): Add per-node FABNet L3 connectivity.
              true or "IPv4" → FABNetv4, "IPv6" → FABNetv6, {"type": "IPv4"} for explicit.

        add_components: List of components to add to EXISTING nodes. Each is a dict with:
            - node (str, required): Name of existing node to add component to
            - model (str, required): Component model (GPU_TeslaT4, NIC_ConnectX_6, etc.)
            - name (str, optional): Component name

        add_switches: List of P4 switches to add. Each is a dict with:
            - name (str, required): Unique switch name
            - site (str, required): FABRIC site where the switch is located

        add_facility_ports: List of facility ports to add. Each is a dict with:
            - name (str, required): Facility port name (e.g., "Cloud-Facility-STAR")
            - site (str, required): FABRIC site
            - vlan (str/int, required): VLAN ID for the facility port interface

        add_networks: List of networks to add. Each is a dict with:
            - name (str, required): Network name
            - nodes (list): Simple form - node names to connect (auto-creates NICs)
            - interfaces (list): Detailed form for port control:
                Node interface:
                - node (str): Node name
                - nic (str, optional): NIC name (reuse existing or create named)
                - component (str, optional): Existing component name (e.g., FPGA)
                - port (int, optional): Port index (0 or 1 for SmartNICs)
                - nic_model (str, optional): NIC model for this interface
                Switch interface:
                - switch (str): P4 switch name
                - port (int, optional): Switch port index (default: 0)
                Facility port interface:
                - facility_port (str): Facility port name
            - type (str, optional): Network type (L2STS, L2Bridge, FABNetv4, etc.)
              L2PTP is only used with ERO for dedicated QoS. Cross-site L2
              defaults to L2STS.
            - ero (list, optional): Explicit Route Option - list of intermediate site
              hops. Forces L2PTP with dedicated QoS. Example: ["WASH", "STAR"]
            - bandwidth (int, optional): Bandwidth in Gbps (L2PTP with ERO only)
            - nic (str, optional): Default NIC model override
            - subnet (str, optional): IPv4 subnet for L2 networks (e.g., "192.168.1.0/24")

        add_port_mirrors: List of port mirror specs to add. Each is a dict with:
            - name (str, required): Mirror service name
            - mirror_interface_name (str, required): Raw name of the interface to mirror
            - receive_interface (dict, required): Interface spec for the receive port
              (node+nic or node+component format)
            - mirror_direction (str, optional): "port" (ingress only) or "both"
              (ingress + egress). Default: "both"

        remove_port_mirrors: List of port mirror service names to remove.

        remove_networks: List of network names to remove from the slice.

        remove_facility_ports: List of facility port names to remove.

        remove_switches: List of switch names to remove.

        remove_components: List of components to remove. Each is a dict with:
            - node (str, required): Node name containing the component
            - name (str, required): Component name to remove

        remove_nodes: List of node names to remove from the slice.

    Returns:
        Dict with modification results:
        - status: "submitted"
        - slice_name, slice_id: Slice identifiers
        - added: {nodes, components, switches, facility_ports, networks, port_mirrors}
        - removed: {nodes, components, switches, facility_ports, networks, port_mirrors}

    Note:
        - Remove order: port_mirrors → networks → facility_ports → switches → components → nodes
        - Add order: nodes → components → switches → facility_ports → networks → port_mirrors
        - The slice is submitted with wait=False (non-blocking)
        - Use fabric_query_slices to check slice state after modification
    """
    headers = get_http_headers(include={"authorization"}) or {}
    id_token = extract_bearer_token(headers)

    if not slice_name and not slice_id:
        raise ValueError("Either slice_name or slice_id must be provided")

    has_add = (add_nodes or add_components or add_switches or
               add_facility_ports or add_networks or add_port_mirrors)
    has_remove = (remove_nodes or remove_components or remove_switches or
                  remove_facility_ports or remove_networks or remove_port_mirrors)

    if not has_add and not has_remove:
        raise ValueError(
            "At least one add or remove operation must be provided"
        )

    result = await call_threadsafe(
        _modify_slice_resources,
        id_token=id_token,
        slice_name=slice_name,
        slice_id=slice_id,
        add_nodes=add_nodes,
        add_components=add_components,
        add_switches=add_switches,
        add_facility_ports=add_facility_ports,
        add_networks=add_networks,
        add_port_mirrors=add_port_mirrors,
        remove_port_mirrors=remove_port_mirrors,
        remove_networks=remove_networks,
        remove_facility_ports=remove_facility_ports,
        remove_switches=remove_switches,
        remove_components=remove_components,
        remove_nodes=remove_nodes,
    )

    return result

@tool_logger("fabric_accept_modify")
async def accept_modify(
    slice_id: str,
) -> Dict[str, Any]:
    """
    Accept pending slice modifications.

    Args:
        slice_id: UUID of the slice with pending modifications.

    Returns:
        Slice dictionary with updated state.
    """
    fm, id_token = get_fabric_manager()
    accepted = await call_threadsafe(
        fm.accept_modify,
        id_token=id_token,
        slice_id=slice_id,
        return_fmt="dict",
    )
    return accepted


TOOLS = [modify_slice_resources, accept_modify]
