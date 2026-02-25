"""
High-level slice builder tool for FABRIC MCP Server.

Provides a declarative interface to build slices with nodes, components,
and network services using FablibManager from fabrictestbed-extensions.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

from fabrictestbed_extensions.fablib.fablib import FablibManager
from fastmcp.server.dependencies import get_http_headers

from fabric_api_mcp.auth.token import extract_bearer_token
from fabric_api_mcp.config import config
from fabric_api_mcp.dependencies.fablib_factory import create_fablib_manager
from fabric_api_mcp.log_helper.decorators import tool_logger
from fabric_api_mcp.utils.async_helpers import call_threadsafe
from fabric_api_mcp.utils.data_helpers import normalize_list_param

logger = logging.getLogger(__name__)


# Valid component models that can be added to nodes
VALID_GPU_MODELS = ["GPU_TeslaT4", "GPU_RTX6000", "GPU_A40", "GPU_A30"]
VALID_NIC_MODELS = [
    "NIC_Basic", "NIC_ConnectX_5", "NIC_ConnectX_6",
    "NIC_ConnectX_7_100", "NIC_ConnectX_7_400",
]
VALID_STORAGE_MODELS = ["NVME_P4510"]
VALID_FPGA_MODELS = ["FPGA_Xilinx_U280", "FPGA_Xilinx_SN1022"]
VALID_COMPONENT_MODELS = VALID_GPU_MODELS + VALID_NIC_MODELS + VALID_STORAGE_MODELS + VALID_FPGA_MODELS

# Valid network types
VALID_L2_NETWORK_TYPES = ["L2PTP", "L2STS", "L2Bridge"]
VALID_L3_NETWORK_TYPES = [
    "FABNetv4", "FABNetv6", "IPv4", "IPv6",
    "FABNetv4Ext", "FABNetv6Ext", "IPv4Ext", "IPv6Ext",
]
VALID_NETWORK_TYPES = VALID_L2_NETWORK_TYPES + VALID_L3_NETWORK_TYPES

# SmartNIC models (dedicated NICs with multiple ports)
SMARTNIC_MODELS = [
    "NIC_ConnectX_5", "NIC_ConnectX_6",
    "NIC_ConnectX_7_100", "NIC_ConnectX_7_400",
]
DEFAULT_SMARTNIC = "NIC_ConnectX_6"

# Mapping from user-facing L3 type to the string expected by add_l3network
L3_TYPE_MAP = {
    "FABNetv4": "IPv4",
    "FABNetv6": "IPv6",
    "FABNetv4Ext": "IPv4Ext",
    "FABNetv6Ext": "IPv6Ext",
    "IPv4": "IPv4",
    "IPv6": "IPv6",
    "IPv4Ext": "IPv4Ext",
    "IPv6Ext": "IPv6Ext",
}


def _determine_network_type(
    requested_type: Optional[str],
    sites: set,
    ero: Optional[List[str]] = None,
) -> str:
    """
    Auto-detect the final network type based on user request and topology.

    L2PTP is only used when ERO (Explicit Route Option) is specified for
    dedicated QoS / bandwidth guarantees. For cross-site L2 without ERO,
    L2STS is always used.

    Args:
        requested_type: The type the user specified (may be None or generic "L2").
        sites: Set of site names for the connected nodes.
        ero: Explicit Route Option hops. When provided, forces L2PTP.

    Returns:
        Resolved network type string.

    Raises:
        ValueError: If the combination is invalid.
    """
    single_site = len(sites) <= 1

    # ERO forces L2PTP (dedicated QoS with explicit routing)
    if ero:
        if single_site:
            raise ValueError(
                "ERO (Explicit Route Option) requires a multi-site (2-site) network. "
                f"Got sites: {sites}"
            )
        return "L2PTP"

    if requested_type is None:
        # No type specified: single-site → L2Bridge, multi-site → FABNetv4 (per-node)
        return "L2Bridge" if single_site else "FABNetv4"

    upper = requested_type.upper()

    # Generic "L2" shorthand
    if upper == "L2":
        return "L2Bridge" if single_site else "L2STS"

    # Explicit L2Bridge – single-site only
    if requested_type == "L2Bridge":
        if not single_site:
            raise ValueError(
                "L2Bridge networks can only connect nodes on the same site. "
                f"Got sites: {sites}"
            )
        return "L2Bridge"

    # L2PTP without ERO → use L2STS instead (L2PTP is only for ERO/dedicated QoS)
    if requested_type == "L2PTP":
        if single_site:
            raise ValueError(
                "L2PTP requires a multi-site (2-site) network. "
                f"Got sites: {sites}"
            )
        logger.warning(
            "L2PTP requested without ERO; using L2STS instead. "
            "L2PTP is only used with ERO for dedicated QoS. "
            "Specify 'ero' (list of site hops) to use L2PTP."
        )
        return "L2STS"

    # Explicit types passed through
    if requested_type in VALID_NETWORK_TYPES:
        return requested_type

    raise ValueError(
        f"Unknown network type: {requested_type}. "
        f"Valid types: {VALID_NETWORK_TYPES + ['L2']}"
    )


def _get_or_create_interface(
    node: Any,
    node_nics: Dict[str, Dict[str, Any]],
    iface_spec: Dict[str, Any],
    net_name: str,
    default_nic_model: str,
) -> Any:
    """
    Get or create a network interface based on the interface specification.

    Supports three interface sources:
    1. NIC interfaces: create or reuse a NIC component (default)
    2. Component interfaces: use ports from existing components like FPGAs
    3. Sub-interfaces: create VLAN sub-interfaces on SmartNIC ports

    Args:
        node: The node object
        node_nics: Dict tracking NICs per node {node_name: {nic_name: component}}
        iface_spec: Interface specification with optional fields:
            - nic/nic_name: NIC component name (creates or reuses)
            - component: Existing component name (e.g., FPGA) to get interfaces from
            - port: Interface/port index (default: 0)
            - nic_model/model: NIC model for new NICs
            - vlan: VLAN ID for sub-interface creation (requires SmartNIC)
        net_name: Network name (used for auto-generated NIC names)
        default_nic_model: Default NIC model if not specified

    Returns:
        The interface object to connect to the network
    """
    node_name = node.get_name()
    port = iface_spec.get("port", 0)  # Default to port 0
    vlan = iface_spec.get("vlan")  # VLAN for sub-interface
    component_name = iface_spec.get("component")  # Existing component (e.g., FPGA)
    nic_name = iface_spec.get("nic") or iface_spec.get("nic_name")
    nic_model = iface_spec.get("nic_model") or iface_spec.get("model") or default_nic_model

    # Case 1: Use an existing component's interface (e.g., FPGA ports)
    if component_name:
        try:
            component = node.get_component(name=component_name)
        except Exception:
            # Check if it was added in this session via node_nics tracking
            if component_name in node_nics.get(node_name, {}):
                component = node_nics[node_name][component_name]
            else:
                raise ValueError(
                    f"Component '{component_name}' not found on node {node_name}. "
                    f"Ensure the component is defined in the node's 'components' list."
                )

        interfaces = component.get_interfaces()
        if port >= len(interfaces):
            raise ValueError(
                f"Port {port} not available on component {component_name} "
                f"(has {len(interfaces)} ports)."
            )

        iface = interfaces[port]
        logger.info(
            f"Using component {component_name} port {port} on node {node_name}"
        )

        # Sub-interface on component port
        if vlan:
            sub_name = iface_spec.get("sub_name", f"{component_name}-p{port}-vlan{vlan}")
            logger.info(f"Creating sub-interface {sub_name} (VLAN {vlan}) on {component_name} port {port}")
            iface = iface.add_sub_interface(name=sub_name, vlan=str(vlan))

        return iface

    # Case 2: NIC interface (create or reuse)
    if nic_name:
        # Check if this NIC was already added in this session
        if nic_name in node_nics.get(node_name, {}):
            nic = node_nics[node_name][nic_name]
            logger.info(f"Reusing existing NIC {nic_name} port {port} on node {node_name}")
        else:
            # Try to get existing NIC from node
            try:
                nic = node.get_component(name=nic_name)
                logger.info(f"Found existing NIC {nic_name} on node {node_name}")
            except Exception:
                # NIC doesn't exist, create it
                logger.info(f"Creating new NIC {nic_name} ({nic_model}) on node {node_name}")
                nic = node.add_component(model=nic_model, name=nic_name)
                node_nics[node_name][nic_name] = nic
    else:
        # Auto-generate NIC name
        nic_name = f"{node_name}-{net_name}-nic"
        logger.info(f"Creating auto-named NIC {nic_name} ({nic_model}) on node {node_name}")
        nic = node.add_component(model=nic_model, name=nic_name)
        node_nics[node_name][nic_name] = nic

    # Get the specified interface/port
    interfaces = nic.get_interfaces()
    if port >= len(interfaces):
        raise ValueError(
            f"Port {port} not available on NIC {nic_name} (has {len(interfaces)} ports). "
            f"SmartNICs like NIC_ConnectX_5/6/7 have 2 ports (0 and 1)."
        )

    iface = interfaces[port]

    # Sub-interface: create VLAN sub-interface on the NIC port
    if vlan:
        sub_name = iface_spec.get("sub_name", f"{nic_name}-p{port}-vlan{vlan}")
        logger.info(f"Creating sub-interface {sub_name} (VLAN {vlan}) on {nic_name} port {port}")
        iface = iface.add_sub_interface(name=sub_name, vlan=str(vlan))

    return iface


def _resolve_interface(
    iface_spec: Dict[str, Any],
    node_map: Dict[str, Any],
    node_nics: Dict[str, Dict[str, Any]],
    switches_map: Dict[str, Any],
    facility_ports_map: Dict[str, Any],
    net_name: str,
    default_nic_model: str,
) -> Any:
    """
    Unified interface resolution that dispatches based on spec type.

    Supports four interface sources:
    1. Switch interfaces: {"switch": "p4-switch", "port": 0}
    2. Facility port interfaces: {"facility_port": "Cloud-Facility-STAR"}
    3. Component interfaces: {"node": "n1", "component": "fpga1", "port": 0}
    4. NIC interfaces: {"node": "n1", "nic": "nic1", "port": 0} (default)

    Args:
        iface_spec: Interface specification dict
        node_map: Dict of node_name -> node object
        node_nics: Dict tracking NICs per node
        switches_map: Dict of switch_name -> switch object
        facility_ports_map: Dict of fp_name -> facility_port object
        net_name: Network name (for auto-generated NIC names)
        default_nic_model: Default NIC model if not specified

    Returns:
        The resolved interface object
    """
    if "switch" in iface_spec:
        switch_name = iface_spec["switch"]
        if switch_name not in switches_map:
            raise ValueError(
                f"Network {net_name} references unknown switch: {switch_name}"
            )
        switch = switches_map[switch_name]
        port = iface_spec.get("port", 0)
        interfaces = switch.get_interfaces()
        if port >= len(interfaces):
            raise ValueError(
                f"Port {port} not available on switch {switch_name} "
                f"(has {len(interfaces)} ports)."
            )
        logger.info(f"Using switch {switch_name} port {port} for network {net_name}")
        return interfaces[port]

    if "facility_port" in iface_spec:
        fp_name = iface_spec["facility_port"]
        if fp_name not in facility_ports_map:
            raise ValueError(
                f"Network {net_name} references unknown facility port: {fp_name}"
            )
        fp = facility_ports_map[fp_name]
        iface = fp.get_interfaces()[0]
        logger.info(f"Using facility port {fp_name} interface for network {net_name}")
        return iface

    # Node-based interface (component or NIC)
    node_name = iface_spec.get("node")
    if not node_name:
        raise ValueError(
            f"Interface spec for network {net_name} must have 'node', 'switch', "
            f"or 'facility_port' field"
        )
    if node_name not in node_map:
        raise ValueError(f"Network {net_name} references unknown node: {node_name}")

    node = node_map[node_name]
    return _get_or_create_interface(
        node, node_nics, iface_spec, net_name, default_nic_model
    )


def _select_nic_for_network(net_type: str, bandwidth: Optional[int] = None) -> str:
    """
    Choose the NIC model appropriate for the network type and bandwidth.

    NIC selection rules:
    - L2PTP always requires a SmartNIC (bandwidth determines which one)
    - 400 Gbps bandwidth → NIC_ConnectX_7_400
    - 100 Gbps bandwidth → NIC_ConnectX_6
    - 25 Gbps bandwidth → NIC_ConnectX_5
    - No bandwidth or other network types → NIC_Basic
    """
    if net_type == "L2PTP":
        # L2PTP requires SmartNIC; pick based on bandwidth
        if bandwidth and bandwidth >= 400:
            return "NIC_ConnectX_7_400"
        elif bandwidth and bandwidth >= 100:
            return "NIC_ConnectX_6"
        elif bandwidth and bandwidth >= 25:
            return "NIC_ConnectX_5"
        # Default SmartNIC for L2PTP without explicit bandwidth
        return DEFAULT_SMARTNIC
    # All other network types use NIC_Basic
    return "NIC_Basic"


def _get_available_sites(fablib: FablibManager, update: bool = True) -> List[Dict[str, Any]]:
    """
    Get list of available sites with their resource capacities.

    Uses update=False after first call for efficiency when placing multiple nodes.
    """
    site_list = fablib.list_sites(
        output="list",
        quiet=True,
        filter_function=lambda s: s.get("state") == "Active" and s.get("hosts", 0) > 0,
        update=update,
    )
    return site_list


def _select_site_for_node(
    available_sites: List[Dict[str, Any]],
    cores: int,
    ram: int,
    disk: int,
    used_sites: List[str],
) -> str:
    """
    Select a site for a node based on resource requirements.

    Prioritizes sites not already used for diversity.
    """
    import random

    # Filter sites with sufficient resources
    suitable_sites = [
        s for s in available_sites
        if s.get("cores_available", 0) >= cores
        and s.get("ram_available", 0) >= ram
        and s.get("disk_available", 0) >= disk
    ]

    if not suitable_sites:
        raise ValueError(
            f"No sites available with sufficient resources: cores>={cores}, ram>={ram}GB, disk>={disk}GB"
        )

    # Prefer sites not already used
    unused_sites = [s for s in suitable_sites if s.get("name") not in used_sites]

    if unused_sites:
        selected = random.choice(unused_sites)
    else:
        selected = random.choice(suitable_sites)

    return selected.get("name")


def _build_and_submit_slice(
    name: str,
    ssh_keys: List[str],
    id_token: Optional[str] = None,
    nodes: Optional[List[Dict[str, Any]]] = None,
    networks: Optional[List[Dict[str, Any]]] = None,
    switches: Optional[List[Dict[str, Any]]] = None,
    facility_ports: Optional[List[Dict[str, Any]]] = None,
    port_mirrors: Optional[List[Dict[str, Any]]] = None,
    lifetime: Optional[int] = None,
    lease_start_time: Optional[str] = None,
    lease_end_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a slice using FablibManager and submit it.

    This function runs synchronously and should be called via call_threadsafe.
    """
    fablib = create_fablib_manager(id_token)

    # Default to empty list if no nodes provided
    nodes = nodes or []

    # Create a new slice
    logger.info(f"Creating new slice: {name}")
    slice_obj = fablib.new_slice(name=name)

    # Track created nodes for network connections
    node_map: Dict[str, Any] = {}

    # Track used sites to spread nodes across different sites when auto-selecting
    used_sites: List[str] = []

    # Pre-fetch available sites once if any node needs auto-selection
    # This avoids multiple API calls for get_random_site()
    needs_auto_site = any(not node_spec.get("site") for node_spec in nodes)
    available_sites: List[Dict[str, Any]] = []
    if needs_auto_site:
        logger.info("Pre-fetching available sites for auto-selection")
        available_sites = _get_available_sites(fablib, update=True)

    # Add nodes to the slice
    for node_spec in nodes:
        node_name = node_spec["name"]
        site = node_spec.get("site")  # May be None
        cores = node_spec.get("cores", 2)
        ram = node_spec.get("ram", 8)
        disk = node_spec.get("disk", 10)
        image = node_spec.get("image", "default_rocky_8")

        # Auto-select random site if not specified
        if not site:
            site = _select_site_for_node(available_sites, cores, ram, disk, used_sites)
            logger.info(f"Auto-selected site '{site}' for node {node_name}")

        used_sites.append(site)
        logger.info(f"Adding node {node_name} at site {site} (cores={cores}, ram={ram}, disk={disk})")

        node = slice_obj.add_node(
            name=node_name,
            site=site,
            cores=cores,
            ram=ram,
            disk=disk,
            image=image,
        )
        node_map[node_name] = node

        # Add components to the node
        components = node_spec.get("components", [])
        for i, comp_spec in enumerate(components):
            model = comp_spec.get("model")
            comp_name = comp_spec.get("name", f"{node_name}-{model}-{i}")

            if model not in VALID_COMPONENT_MODELS:
                raise ValueError(
                    f"Unknown component model: {model}. "
                    f"Valid models: {VALID_COMPONENT_MODELS}"
                )

            logger.info(f"Adding component {comp_name} ({model}) to node {node_name}")
            node.add_component(model=model, name=comp_name)

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

    # Track NICs added to nodes for reuse (node_name -> {nic_name -> component})
    node_nics: Dict[str, Dict[str, Any]] = {name: {} for name in node_map}

    # Add P4 switches
    switches_map: Dict[str, Any] = {}
    if switches:
        for sw_spec in switches:
            sw_name = sw_spec["name"]
            sw_site = sw_spec["site"]
            logger.info(f"Adding P4 switch {sw_name} at site {sw_site}")
            switch = slice_obj.add_switch(name=sw_name, site=sw_site)
            switches_map[sw_name] = switch

    # Add facility ports
    facility_ports_map: Dict[str, Any] = {}
    if facility_ports:
        for fp_spec in facility_ports:
            fp_name = fp_spec["name"]
            fp_site = fp_spec["site"]
            fp_vlan = fp_spec["vlan"]
            logger.info(f"Adding facility port {fp_name} at site {fp_site} (VLAN {fp_vlan})")
            fp = slice_obj.add_facility_port(
                name=fp_name, site=fp_site, vlan=str(fp_vlan)
            )
            facility_ports_map[fp_name] = fp

    # In local mode, default interface mode to "auto" so post_boot_config
    # will automatically allocate and configure IPs. Users can override per
    # interface via "mode" in the interface spec. In server mode we do not
    # set mode (no SSH access for post_boot_config).
    set_iface_mode = config.local_mode

    # Add networks to connect nodes/switches/facility_ports
    if networks:
        for net_spec in networks:
            net_name = net_spec["name"]
            requested_type = net_spec.get("type")
            bandwidth = net_spec.get("bandwidth")
            user_nic_model = net_spec.get("nic") or net_spec.get("nic_model")
            ero = net_spec.get("ero")  # Explicit Route Option: list of site hops

            # Support two formats:
            # 1. Simple: "nodes": ["node1", "node2"] - auto-create NICs
            # 2. Detailed: "interfaces": [{"node": ..., "switch": ..., "facility_port": ...}, ...]
            connected_nodes = net_spec.get("nodes", [])
            interface_specs = net_spec.get("interfaces", [])

            # Convert simple node list to interface specs if needed
            if connected_nodes and not interface_specs:
                interface_specs = [{"node": n} for n in connected_nodes]

            if len(interface_specs) < 2:
                raise ValueError(
                    f"Network {net_name} must connect at least 2 nodes/interfaces"
                )

            # Collect sites from all interface endpoints for type determination
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

            # Resolve the final network type
            net_type = _determine_network_type(requested_type, net_sites, ero=ero)

            logger.info(
                f"Adding network {net_name} (requested={requested_type}, "
                f"resolved={net_type})"
            )

            # Select NIC model: user-specified takes precedence, otherwise auto-select
            if user_nic_model:
                if user_nic_model not in VALID_NIC_MODELS:
                    raise ValueError(
                        f"Invalid NIC model '{user_nic_model}' for network {net_name}. "
                        f"Valid models: {VALID_NIC_MODELS}"
                    )
                nic_model = user_nic_model
                logger.info(f"Using user-specified NIC model: {nic_model}")
            else:
                nic_model = _select_nic_for_network(net_type, bandwidth)

            # Check if this is a FABNet* type (L3 network that needs per-site handling)
            fabnet_types = ["FABNetv4", "FABNetv6", "FABNetv4Ext", "FABNetv6Ext"]
            is_fabnet = net_type in fabnet_types

            # Handle multi-site FABNet* networks: create per-site networks
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

                    logger.info(
                        f"Creating per-site {net_type} network {site_net_name} at site {site}"
                    )
                    slice_obj.add_l3network(
                        name=site_net_name,
                        interfaces=site_interfaces,
                        type=l3_type,
                    )
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

            # Create L3 or L2 network
            if net_type in VALID_L3_NETWORK_TYPES:
                l3_type = L3_TYPE_MAP[net_type]
                logger.info(f"Creating L3 network {net_name} of type {l3_type}")
                slice_obj.add_l3network(name=net_name, interfaces=interfaces, type=l3_type)
            else:
                logger.info(f"Creating L2 network {net_name} (type={net_type})")
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
                    logger.info(f"Setting bandwidth to {bandwidth} Gbps for network {net_name}")
                    net_service.set_bandwidth(bw=bandwidth)

    # Add port mirror services (after networks, needs interfaces to exist)
    if port_mirrors:
        for pm_spec in port_mirrors:
            pm_name = pm_spec["name"]
            mirror_iface_name = pm_spec["mirror_interface_name"]
            receive_spec = pm_spec["receive_interface"]
            direction = pm_spec.get("mirror_direction", "both")

            logger.info(
                f"Adding port mirror {pm_name}: mirror={mirror_iface_name}, "
                f"direction={direction}"
            )

            # Resolve the receive interface
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

    # Submit the slice (non-blocking)
    logger.info(f"Submitting slice {name}")

    # Convert lifetime to lease_in_hours if provided
    lease_in_hours = lifetime * 24 if lifetime else None

    slice_id = slice_obj.submit(
        wait=False,  # Don't wait for slice to be ready
        progress=False,
        post_boot_config=False,
        wait_ssh=False,
        extra_ssh_keys=ssh_keys,
        lease_in_hours=lease_in_hours,
    )

    logger.info(f"Slice {name} submitted successfully with ID: {slice_id}")

    return {
        "status": "submitted",
        "slice_id": slice_id,
        "slice_name": name,
        "nodes": [n["name"] for n in nodes],
        "switches": [s["name"] for s in switches] if switches else [],
        "facility_ports": [f["name"] for f in facility_ports] if facility_ports else [],
        "networks": [n["name"] for n in networks] if networks else [],
        "port_mirrors": [p["name"] for p in port_mirrors] if port_mirrors else [],
    }


@tool_logger("fabric_build_slice")
async def build_slice(
    name: str,
    ssh_keys: Optional[Union[str, List[str]]] = None,
    nodes: Optional[Union[str, List[Dict[str, Any]]]] = None,
    networks: Optional[Union[str, List[Dict[str, Any]]]] = None,
    switches: Optional[Union[str, List[Dict[str, Any]]]] = None,
    facility_ports: Optional[Union[str, List[Dict[str, Any]]]] = None,
    port_mirrors: Optional[Union[str, List[Dict[str, Any]]]] = None,
    lifetime: Optional[int] = None,
    lease_start_time: Optional[str] = None,
    lease_end_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build and create a FABRIC slice from high-level specifications.

    This tool provides a declarative way to create slices without needing to
    construct raw GraphML. Specify nodes with their sites and components,
    and networks to connect them.

    Args:
        name: Name of the slice to create.

        ssh_keys: SSH public keys for slice access. Can be a list or JSON string.
                  In local mode, if omitted, the public key is automatically read
                  from the file at FABRIC_SLICE_PUBLIC_KEY_FILE (set in fabric_rc).

        nodes: List of node specifications (optional). Required when creating VMs.
            Omit for facility-port-only or switch-only slices. Each node is a dict with:
            - name (str, required): Unique node name
            - site (str, optional): FABRIC site (e.g., "UTAH", "STAR", "UCSD", "WASH").
              If omitted, a random site with sufficient resources is auto-selected.
              Sites are chosen to spread nodes across different locations when possible.
            - cores (int, optional): CPU cores (default: 2)
            - ram (int, optional): RAM in GB (default: 8)
            - disk (int, optional): Disk in GB (default: 10)
            - image (str, optional): OS image (default: "default_rocky_8")
            - components (list, optional): List of components to add:
                - model (str): Component model.
                  GPUs: "GPU_TeslaT4", "GPU_RTX6000", "GPU_A40", "GPU_A30"
                  NICs: "NIC_Basic", "NIC_ConnectX_5", "NIC_ConnectX_6",
                        "NIC_ConnectX_7_100" (100G BlueField-3),
                        "NIC_ConnectX_7_400" (400G BlueField-3)
                  FPGAs: "FPGA_Xilinx_U280", "FPGA_Xilinx_SN1022"
                  Storage: "NVME_P4510"
                - name (str, optional): Component name (used to reference in networks)
            - fabnet (bool/str/dict, optional): Add per-node FABNet L3 connectivity.
              Useful for nodes that need external access (e.g., FPGA nodes that need
              to download tools/artifacts). Creates a site-scoped L3 network with
              NIC_Basic and sets up routes automatically.
                * true or "IPv4" → FABNetv4 (default)
                * "IPv6" → FABNetv6
                * {"type": "IPv4"} or {"type": "IPv6"} → explicit type

        networks: List of network specifications. Each network is a dict with:
            - name (str, required): Network name
            - nodes (list): Simple form - list of node names to connect (auto-creates NICs)
            - interfaces (list): Detailed form - list of interface specs. Each spec can
              reference a node, switch, or facility port:
                Node interface:
                - node (str): Node name
                - nic (str, optional): NIC component name (reuse existing or create named)
                - component (str, optional): Existing component name (e.g., FPGA) to
                  use interfaces from. Mutually exclusive with "nic".
                - port (int, optional): Interface/port index (default: 0).
                - vlan (str/int, optional): VLAN ID for sub-interface creation.
                - nic_model (str, optional): NIC model for new NICs
                - mode (str, optional): Interface configuration mode (local mode only).
                  Defaults to "auto". Values: "auto" (auto-allocate IP from network),
                  "config" (use pre-assigned IP), "manual" (no auto-config).
                  Ignored in server mode.
                Switch interface:
                - switch (str): P4 switch name
                - port (int, optional): Switch port index (default: 0)
                Facility port interface:
                - facility_port (str): Facility port name
              Use "interfaces" to connect nodes, switches, FPGAs, facility ports,
              or VLAN sub-interfaces to networks.
            - type (str, optional): Network type. Auto-detected if omitted:
                * Single-site, no type → L2Bridge
                * Multi-site, no type → per-site FABNetv4 (see below)
                * "L2" (generic) → L2Bridge (single-site) or L2STS (multi-site)
              Explicit types:
                "L2STS" (site-to-site, default for cross-site L2),
                "L2Bridge" (local bridge, single site only),
                "L2PTP" (point-to-point with ERO; requires 'ero' parameter),
                "FABNetv4", "FABNetv6" (L3 networks),
                "FABNetv4Ext", "FABNetv6Ext" (externally reachable L3),
                "IPv4", "IPv6", "IPv4Ext", "IPv6Ext"

              **L2PTP vs L2STS:** L2PTP is only used when ERO (Explicit Route Option)
              is specified for dedicated QoS and bandwidth guarantees. For cross-site
              L2 without ERO, L2STS is always used. If L2PTP is requested without
              ERO, it is automatically converted to L2STS.

              **Multi-site FABNet* handling:** When nodes span multiple sites and
              a FABNet* type is used (FABNetv4, FABNetv6, FABNetv4Ext, FABNetv6Ext),
              the builder creates one network PER SITE, connecting all nodes at
              that site to their site-specific network. Network names are suffixed
              with the site name (e.g., "mynet-UTAH", "mynet-STAR"). This is required
              because FABNet services are site-scoped.
            - ero (list, optional): Explicit Route Option - list of intermediate site
              names (hops) for the L2 path. When specified, forces L2PTP type with
              dedicated QoS. Requires exactly 2 interfaces across 2 sites.
              Example: ["STAR", "WASH"] routes traffic through STAR and WASH.
            - bandwidth (int, optional): Bandwidth in Gbps (L2PTP with ERO only).
              Also determines NIC model selection (if nic not specified):
                * 400 Gbps → NIC_ConnectX_7_400
                * 100 Gbps → NIC_ConnectX_6
                * 25 Gbps → NIC_ConnectX_5
                * No bandwidth or other types → NIC_Basic
            - nic (str, optional): Explicit NIC model to use for this network.
              Overrides automatic selection. Valid models:
                "NIC_Basic", "NIC_ConnectX_5", "NIC_ConnectX_6",
                "NIC_ConnectX_7_100", "NIC_ConnectX_7_400"

        switches: List of P4 switch specifications. Each switch is a dict with:
            - name (str, required): Unique switch name
            - site (str, required): FABRIC site where the switch is located

        facility_ports: List of facility port specifications. Each is a dict with:
            - name (str, required): Facility port name (e.g., "Cloud-Facility-STAR")
            - site (str, required): FABRIC site
            - vlan (str/int, required): VLAN ID for the facility port interface

        port_mirrors: List of port mirror specifications. Each is a dict with:
            - name (str, required): Mirror service name
            - mirror_interface_name (str, required): Raw name of the interface to mirror
              (the infrastructure interface name string)
            - receive_interface (dict, required): Interface spec for the receive port.
              Uses the same format as network interface specs (node+nic or node+component).
            - mirror_direction (str, optional): "port" (ingress only) or "both"
              (ingress + egress). Default: "both"

        lifetime: Slice lifetime in days (optional).

        lease_start_time: Lease start time in UTC format (optional).

        lease_end_time: Lease end time in UTC format (optional).

    Returns:
        Dict with slice creation status and details.

    Example:
        Create 2 GPU nodes (Utah and DC) connected by cross-site L2 network:

        {
            "name": "my-gpu-slice",
            "ssh_keys": ["ssh-rsa AAAA..."],
            "nodes": [
                {
                    "name": "node-utah",
                    "site": "UTAH",
                    "cores": 16,
                    "ram": 64,
                    "disk": 100,
                    "components": [
                        {"model": "GPU_TeslaT4", "name": "gpu1"}
                    ]
                },
                {
                    "name": "node-dc",
                    "site": "STAR",
                    "cores": 16,
                    "ram": 64,
                    "disk": 100,
                    "components": [
                        {"model": "GPU_TeslaT4", "name": "gpu1"}
                    ]
                }
            ],
            "networks": [
                {
                    "name": "gpu-net",
                    "nodes": ["node-utah", "node-dc"],
                    "type": "L2STS"
                }
            ]
        }

        With ERO for dedicated QoS (100 Gbps with explicit routing):

        {
            "networks": [
                {
                    "name": "gpu-link",
                    "nodes": ["node-utah", "node-dc"],
                    "ero": ["WASH", "STAR"],
                    "bandwidth": 100
                }
            ]
        }

        FPGA nodes connected via L2 network (FPGA-to-FPGA WAN):

        {
            "name": "fpga-wan-slice",
            "ssh_keys": ["ssh-rsa AAAA..."],
            "nodes": [
                {
                    "name": "fpga-node-1",
                    "site": "PSC",
                    "cores": 8,
                    "disk": 100,
                    "image": "docker_ubuntu_20",
                    "components": [{"model": "FPGA_Xilinx_U280", "name": "fpga1"}],
                    "fabnet": true
                },
                {
                    "name": "fpga-node-2",
                    "site": "INDI",
                    "cores": 8,
                    "disk": 100,
                    "image": "docker_ubuntu_20",
                    "components": [{"model": "FPGA_Xilinx_U280", "name": "fpga1"}],
                    "fabnet": true
                }
            ],
            "networks": [
                {
                    "name": "fpga-link",
                    "interfaces": [
                        {"node": "fpga-node-1", "component": "fpga1", "port": 1},
                        {"node": "fpga-node-2", "component": "fpga1", "port": 0}
                    ],
                    "type": "L2STS"
                }
            ]
        }

        Sub-interfaces (multiple VLANs on same SmartNIC port):

        {
            "networks": [
                {
                    "name": "vlan100-net",
                    "interfaces": [
                        {"node": "node1", "nic": "smartnic1", "port": 0, "vlan": 100},
                        {"node": "node2", "nic": "smartnic1", "port": 0, "vlan": 100}
                    ],
                    "type": "L2Bridge"
                },
                {
                    "name": "vlan200-net",
                    "interfaces": [
                        {"node": "node1", "nic": "smartnic1", "port": 0, "vlan": 200},
                        {"node": "node2", "nic": "smartnic1", "port": 0, "vlan": 200}
                    ],
                    "type": "L2Bridge"
                }
            ]
        }

    SSH Access to VMs:
        After the slice reaches StableOK state, access VMs via SSH through the
        FABRIC bastion host.

        Prerequisites:
        1. Bastion keys - Create at https://portal.fabric-testbed.net/experiments#sshKeys
        2. Slice SSH keys - The ssh_keys provided to this tool (stored on VMs)
        3. Bastion login - Get via get-user-info tool (returns bastion_login field)

        SSH Config (~/.ssh/config):
            UserKnownHostsFile /dev/null
            StrictHostKeyChecking no
            ServerAliveInterval 120

            Host bastion.fabric-testbed.net
                User <bastion_login>
                ForwardAgent yes
                Hostname %h
                IdentityFile ~/.ssh/bastion_key
                IdentitiesOnly yes

            Host * !bastion.fabric-testbed.net
                ProxyJump <bastion_login>@bastion.fabric-testbed.net:22

        SSH Command:
            ssh -i /path/to/slice_key -F /path/to/ssh_config ubuntu@<vm_management_ip>

        Notes:
        - VM management IP (IPv6) is available from get-slivers output
        - Default username is 'ubuntu' for Rocky/Ubuntu images
        - Replace <bastion_login> with your bastion username (e.g., kthare10_0011904101)

    IP Assignment by Network Type:
        After slice reaches StableOK, configure network interfaces inside VMs:

        L2 Networks (L2PTP, L2STS, L2Bridge):
            - User chooses any subnet (e.g., 192.168.1.0/24)
            - Assign IPs manually to VM interfaces via SSH

        L3 Networks (FABNetv4, FABNetv6):
            - Orchestrator assigns the subnet automatically
            - Use get-network-info to see assigned subnet and gateway
            - Assign IPs from that subnet to VM interfaces

        L3 Ext Networks (FABNetv4Ext, FABNetv6Ext):
            - Orchestrator assigns the subnet
            - Call make-ip-publicly-routable to enable external access
            - Configure the RETURNED public_ips value inside your VM

        FABNetv4Ext vs FABNetv6Ext:
            - FABNetv4Ext: IPv4 subnet is SHARED across all slices at site.
              Requested IP may be in use; orchestrator returns actual available IP.
              Always use the RETURNED public_ips value.
            - FABNetv6Ext: Entire IPv6 subnet is DEDICATED to your slice.
              Any IP from the subnet can be requested and used.
    """
    # Extract bearer token from request
    headers = get_http_headers(include={"authorization"}) or {}
    id_token = extract_bearer_token(headers)

    # Normalize list parameters that may be passed as JSON strings
    ssh_keys = normalize_list_param(ssh_keys, "ssh_keys") or []

    # In local mode, ssh_keys can be empty — FablibManager reads the public key
    # from FABRIC_SLICE_PUBLIC_KEY_FILE (set in fabric_rc) automatically.
    # In server mode, ssh_keys are required.
    if not ssh_keys and not config.local_mode:
        raise ValueError("ssh_keys are required in server mode. Provide at least one SSH public key.")

    # Parse nodes if passed as JSON string, default to empty list if omitted
    if nodes is not None:
        if isinstance(nodes, str):
            try:
                nodes = json.loads(nodes)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse nodes JSON: {e}")
    else:
        nodes = []

    # Parse JSON string parameters
    def _parse_json_param(val, param_name):
        if val is not None and isinstance(val, str):
            try:
                return json.loads(val)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse {param_name} JSON: {e}")
        return val

    networks = _parse_json_param(networks, "networks")
    switches = _parse_json_param(switches, "switches")
    facility_ports = _parse_json_param(facility_ports, "facility_ports")
    port_mirrors = _parse_json_param(port_mirrors, "port_mirrors")

    # Validate node specifications
    if not isinstance(nodes, list):
        raise ValueError("nodes must be a list of node specifications")
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValueError(f"Node {i} must be a dictionary, got {type(node)}")
        if "name" not in node:
            raise ValueError(f"Node {i} missing required 'name' field")
        # Note: 'site' is optional - if not provided, a random site will be selected

    # Validate switch specifications
    if switches:
        for i, sw in enumerate(switches):
            if not isinstance(sw, dict):
                raise ValueError(f"Switch {i} must be a dictionary")
            if "name" not in sw:
                raise ValueError(f"Switch {i} missing required 'name' field")
            if "site" not in sw:
                raise ValueError(f"Switch {i} missing required 'site' field")

    # Validate facility port specifications
    if facility_ports:
        for i, fp in enumerate(facility_ports):
            if not isinstance(fp, dict):
                raise ValueError(f"Facility port {i} must be a dictionary")
            if "name" not in fp:
                raise ValueError(f"Facility port {i} missing required 'name' field")
            if "site" not in fp:
                raise ValueError(f"Facility port {i} missing required 'site' field")
            if "vlan" not in fp:
                raise ValueError(f"Facility port {i} missing required 'vlan' field")

    # Validate port mirror specifications
    if port_mirrors:
        for i, pm in enumerate(port_mirrors):
            if not isinstance(pm, dict):
                raise ValueError(f"Port mirror {i} must be a dictionary")
            if "name" not in pm:
                raise ValueError(f"Port mirror {i} missing required 'name' field")
            if "mirror_interface_name" not in pm:
                raise ValueError(f"Port mirror {i} missing required 'mirror_interface_name' field")
            if "receive_interface" not in pm:
                raise ValueError(f"Port mirror {i} missing required 'receive_interface' field")

    # Build and submit the slice
    logger.info(f"Building slice '{name}' with {len(nodes)} nodes")
    result = await call_threadsafe(
        _build_and_submit_slice,
        id_token=id_token,
        name=name,
        ssh_keys=ssh_keys,
        nodes=nodes,
        networks=networks,
        switches=switches,
        facility_ports=facility_ports,
        port_mirrors=port_mirrors,
        lifetime=lifetime,
        lease_start_time=lease_start_time,
        lease_end_time=lease_end_time,
    )

    return result


TOOLS = [build_slice]
