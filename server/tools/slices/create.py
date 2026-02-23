"""
High-level slice builder tool for FABRIC MCP Server.

Provides a declarative interface to build slices with nodes, components,
and network services using FablibManager from fabrictestbed-extensions.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

from fabrictestbed_extensions.fablib.fablib_v2 import FablibManagerV2
from fastmcp.server.dependencies import get_http_headers

from server.auth.token import extract_bearer_token
from server.dependencies.fablib_factory import create_fablib_manager
from server.log_helper.decorators import tool_logger
from server.utils.async_helpers import call_threadsafe
from server.utils.data_helpers import normalize_list_param

logger = logging.getLogger(__name__)


# Valid component models that can be added to nodes
VALID_GPU_MODELS = ["GPU_TeslaT4", "GPU_RTX6000", "GPU_A40", "GPU_A30"]
VALID_NIC_MODELS = ["NIC_Basic", "NIC_ConnectX_5", "NIC_ConnectX_6", "NIC_ConnectX_7_100"]
VALID_STORAGE_MODELS = ["NVME_P4510"]
VALID_FPGA_MODELS = ["FPGA_Xilinx_U280"]
VALID_COMPONENT_MODELS = VALID_GPU_MODELS + VALID_NIC_MODELS + VALID_STORAGE_MODELS + VALID_FPGA_MODELS

# Valid network types
VALID_L2_NETWORK_TYPES = ["L2PTP", "L2STS", "L2Bridge"]
VALID_L3_NETWORK_TYPES = [
    "FABNetv4", "FABNetv6", "IPv4", "IPv6",
    "FABNetv4Ext", "FABNetv6Ext", "IPv4Ext", "IPv6Ext",
]
VALID_NETWORK_TYPES = VALID_L2_NETWORK_TYPES + VALID_L3_NETWORK_TYPES

# SmartNIC models required for L2PTP
SMARTNIC_MODELS = ["NIC_ConnectX_5", "NIC_ConnectX_6", "NIC_ConnectX_7_100"]
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
) -> str:
    """
    Auto-detect the final network type based on user request and topology.

    Args:
        requested_type: The type the user specified (may be None or generic "L2").
        sites: Set of site names for the connected nodes.

    Returns:
        Resolved network type string.

    Raises:
        ValueError: If the combination is invalid.
    """
    single_site = len(sites) <= 1

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
    Get or create a NIC interface based on the interface specification.

    Args:
        node: The node object
        node_nics: Dict tracking NICs per node {node_name: {nic_name: component}}
        iface_spec: Interface specification with optional nic, port, nic_model
        net_name: Network name (used for auto-generated NIC names)
        default_nic_model: Default NIC model if not specified

    Returns:
        The interface object to connect to the network
    """
    node_name = node.get_name()
    nic_name = iface_spec.get("nic") or iface_spec.get("nic_name")
    port = iface_spec.get("port", 0)  # Default to port 0
    nic_model = iface_spec.get("nic_model") or iface_spec.get("model") or default_nic_model

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
            f"SmartNICs like NIC_ConnectX_5/6 have 2 ports (0 and 1)."
        )

    return interfaces[port]


def _select_nic_for_network(net_type: str, bandwidth: Optional[int] = None) -> str:
    """
    Choose the NIC model appropriate for the network type and bandwidth.

    NIC selection rules:
    - L2PTP always requires a SmartNIC (bandwidth determines which one)
    - 100 Gbps bandwidth → NIC_ConnectX_6
    - 25 Gbps bandwidth → NIC_ConnectX_5
    - No bandwidth or other network types → NIC_Basic
    """
    if net_type == "L2PTP":
        # L2PTP requires SmartNIC; pick based on bandwidth
        if bandwidth and bandwidth >= 100:
            return "NIC_ConnectX_6"
        elif bandwidth and bandwidth >= 25:
            return "NIC_ConnectX_5"
        # Default SmartNIC for L2PTP without explicit bandwidth
        return DEFAULT_SMARTNIC
    # All other network types use NIC_Basic
    return "NIC_Basic"


def _get_available_sites(fablib: FablibManagerV2, update: bool = True) -> List[Dict[str, Any]]:
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
    id_token: str,
    name: str,
    ssh_keys: List[str],
    nodes: List[Dict[str, Any]],
    networks: Optional[List[Dict[str, Any]]] = None,
    lifetime: Optional[int] = None,
    lease_start_time: Optional[str] = None,
    lease_end_time: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a slice using FablibManager and submit it.

    This function runs synchronously and should be called via call_threadsafe.
    """
    fablib = create_fablib_manager(id_token)

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

    # Track NICs added to nodes for reuse (node_name -> {nic_name -> component})
    node_nics: Dict[str, Dict[str, Any]] = {name: {} for name in node_map}

    # Add networks to connect nodes
    if networks:
        for net_spec in networks:
            net_name = net_spec["name"]
            requested_type = net_spec.get("type")
            bandwidth = net_spec.get("bandwidth")
            user_nic_model = net_spec.get("nic") or net_spec.get("nic_model")

            # Support two formats:
            # 1. Simple: "nodes": ["node1", "node2"] - auto-create NICs
            # 2. Detailed: "interfaces": [{"node": "node1", "nic": "nic1", "port": 0}, ...]
            connected_nodes = net_spec.get("nodes", [])
            interface_specs = net_spec.get("interfaces", [])

            # Convert simple node list to interface specs if needed
            if connected_nodes and not interface_specs:
                interface_specs = [{"node": n} for n in connected_nodes]
            elif interface_specs:
                # Extract node names from interface specs
                connected_nodes = [ispec.get("node") for ispec in interface_specs]

            if len(interface_specs) < 2:
                raise ValueError(
                    f"Network {net_name} must connect at least 2 nodes/interfaces"
                )

            # Validate all referenced nodes exist
            for node_name in connected_nodes:
                if node_name not in node_map:
                    raise ValueError(f"Network {net_name} references unknown node: {node_name}")

            # Collect sites to determine single-site vs multi-site
            net_sites = {node_map[n].get_site() for n in connected_nodes}

            # Resolve the final network type
            net_type = _determine_network_type(requested_type, net_sites)

            logger.info(
                f"Adding network {net_name} (requested={requested_type}, "
                f"resolved={net_type}) connecting nodes: {connected_nodes}"
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

            # Build a map of interface specs by node name for quick lookup
            iface_spec_by_node = {ispec.get("node"): ispec for ispec in interface_specs}

            # Handle multi-site FABNet* networks: create per-site networks
            if is_fabnet and len(net_sites) > 1:
                # Group interface specs by site
                specs_by_site: Dict[str, List[Dict[str, Any]]] = {}
                for ispec in interface_specs:
                    node_name = ispec.get("node")
                    node_site = node_map[node_name].get_site()
                    if node_site not in specs_by_site:
                        specs_by_site[node_site] = []
                    specs_by_site[node_site].append(ispec)

                # Create a per-site FABNet network connecting all nodes at that site
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
                        site_interfaces.append(iface)

                    site_node_names = [s.get("node") for s in site_specs]
                    logger.info(
                        f"Creating per-site {net_type} network {site_net_name} "
                        f"at site {site} connecting nodes: {site_node_names}"
                    )
                    slice_obj.add_l3network(
                        name=site_net_name,
                        interfaces=site_interfaces,
                        type=l3_type,
                    )
                continue

            # Add NIC interfaces for each interface spec
            interfaces = []
            for ispec in interface_specs:
                node_name = ispec.get("node")
                node = node_map[node_name]
                iface = _get_or_create_interface(
                    node, node_nics, ispec, net_name, nic_model
                )
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

                # Bandwidth only applies to L2PTP
                if bandwidth and net_type == "L2PTP":
                    logger.info(f"Setting bandwidth to {bandwidth} Gbps for network {net_name}")
                    net_service.set_bandwidth(bw=bandwidth)

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
        "networks": [n["name"] for n in networks] if networks else [],
    }


@tool_logger("fabric_build_slice")
async def build_slice(
    name: str,
    ssh_keys: Union[str, List[str]],
    nodes: Union[str, List[Dict[str, Any]]],
    networks: Optional[Union[str, List[Dict[str, Any]]]] = None,
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

        nodes: List of node specifications. Each node is a dict with:
            - name (str, required): Unique node name
            - site (str, optional): FABRIC site (e.g., "UTAH", "STAR", "UCSD", "WASH").
              If omitted, a random site with sufficient resources is auto-selected.
              Sites are chosen to spread nodes across different locations when possible.
            - cores (int, optional): CPU cores (default: 2)
            - ram (int, optional): RAM in GB (default: 8)
            - disk (int, optional): Disk in GB (default: 10)
            - image (str, optional): OS image (default: "default_rocky_8")
            - components (list, optional): List of components to add:
                - model (str): Component model. Valid GPU models:
                    "GPU_TeslaT4", "GPU_RTX6000", "GPU_A40", "GPU_A30"
                  Valid NIC models:
                    "NIC_Basic", "NIC_ConnectX_5", "NIC_ConnectX_6"
                - name (str, optional): Component name

        networks: List of network specifications. Each network is a dict with:
            - name (str, required): Network name
            - nodes (list): Simple form - list of node names to connect (auto-creates NICs)
            - interfaces (list): Detailed form - list of interface specs for SmartNIC control:
                - node (str, required): Node name
                - nic (str, optional): NIC component name (reuse existing or create named)
                - port (int, optional): Interface/port index (0 or 1 for SmartNICs, default: 0)
                - nic_model (str, optional): NIC model for this interface
              Use "interfaces" to connect multiple networks to different ports of the same
              SmartNIC. Example: one SmartNIC with port 0 → net1, port 1 → net2.
            - type (str, optional): Network type. Auto-detected if omitted:
                * Single-site, no type → L2Bridge
                * Multi-site, no type → per-site FABNetv4 (see below)
                * "L2" (generic) → L2Bridge (single-site) or L2STS (multi-site)
              Explicit types:
                "L2PTP" (point-to-point; requires SmartNIC, auto-added),
                "L2STS" (site-to-site, multiple interfaces),
                "L2Bridge" (local bridge, single site only),
                "FABNetv4", "FABNetv6" (L3 networks),
                "FABNetv4Ext", "FABNetv6Ext" (externally reachable L3),
                "IPv4", "IPv6", "IPv4Ext", "IPv6Ext"

              **Multi-site FABNet* handling:** When nodes span multiple sites and
              a FABNet* type is used (FABNetv4, FABNetv6, FABNetv4Ext, FABNetv6Ext),
              the builder creates one network PER SITE, connecting all nodes at
              that site to their site-specific network. Network names are suffixed
              with the site name (e.g., "mynet-UTAH", "mynet-STAR"). This is required
              because FABNet services are site-scoped.
            - bandwidth (int, optional): Bandwidth in Gbps (L2PTP only).
              Also determines NIC model selection (if nic not specified):
                * 100 Gbps → NIC_ConnectX_6
                * 25 Gbps → NIC_ConnectX_5
                * No bandwidth or other types → NIC_Basic
            - nic (str, optional): Explicit NIC model to use for this network.
              Overrides automatic selection. Valid models:
                "NIC_Basic", "NIC_ConnectX_5", "NIC_ConnectX_6", "NIC_ConnectX_7_100"

        lifetime: Slice lifetime in days (optional).

        lease_start_time: Lease start time in UTC format (optional).

        lease_end_time: Lease end time in UTC format (optional).

    Returns:
        Dict with slice creation status and details.

    Example:
        Create 2 GPU nodes (Utah and DC) connected by 100 Gbps network:

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
                    "type": "L2PTP",
                    "bandwidth": 100
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
    headers = get_http_headers() or {}
    id_token = extract_bearer_token(headers)

    # Normalize list parameters that may be passed as JSON strings
    ssh_keys = normalize_list_param(ssh_keys, "ssh_keys") or []

    # Parse nodes if passed as JSON string
    if isinstance(nodes, str):
        try:
            nodes = json.loads(nodes)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse nodes JSON: {e}")

    if not isinstance(nodes, list) or len(nodes) == 0:
        raise ValueError("nodes must be a non-empty list of node specifications")

    # Parse networks if passed as JSON string
    if networks is not None:
        if isinstance(networks, str):
            try:
                networks = json.loads(networks)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse networks JSON: {e}")

    # Validate node specifications
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValueError(f"Node {i} must be a dictionary, got {type(node)}")
        if "name" not in node:
            raise ValueError(f"Node {i} missing required 'name' field")
        # Note: 'site' is optional - if not provided, a random site will be selected

    # Build and submit the slice
    logger.info(f"Building slice '{name}' with {len(nodes)} nodes")
    result = await call_threadsafe(
        _build_and_submit_slice,
        id_token=id_token,
        name=name,
        ssh_keys=ssh_keys,
        nodes=nodes,
        networks=networks,
        lifetime=lifetime,
        lease_start_time=lease_start_time,
        lease_end_time=lease_end_time,
    )

    return result


TOOLS = [build_slice]
