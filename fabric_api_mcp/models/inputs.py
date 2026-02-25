"""
Pydantic input models for all FABRIC MCP tools.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared base models
# ---------------------------------------------------------------------------

class SortSpec(BaseModel):
    """Sort specification."""
    field: str = Field(..., description="Field name to sort by")
    direction: str = Field("asc", description="Sort direction: 'asc' or 'desc'")


class FilterParams(BaseModel):
    """Common filter/sort/pagination parameters for query tools."""
    filters: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Declarative JSON filter DSL. Operators: eq, ne, lt, lte, gt, gte, "
            "in, contains, icontains, regex, any, all. "
            "Logical OR: {\"or\": [{...}, {...}]}. "
            "Example: {\"cores_available\": {\"gte\": 32}}"
        ),
    )
    sort: Optional[Dict[str, Any]] = Field(
        None,
        description='Sort specification: {"field": "<name>", "direction": "asc|desc"}',
    )
    limit: Optional[int] = Field(200, ge=1, le=5000, description="Maximum results to return (default 200)")
    offset: int = Field(0, ge=0, description="Number of results to skip (default 0)")


# ---------------------------------------------------------------------------
# Topology tools
# ---------------------------------------------------------------------------

class QuerySitesInput(FilterParams):
    """Input for fabric_query_sites."""
    pass


class QueryHostsInput(FilterParams):
    """Input for fabric_query_hosts."""
    pass


class QueryFacilityPortsInput(FilterParams):
    """Input for fabric_query_facility_ports."""
    pass


class QueryLinksInput(FilterParams):
    """Input for fabric_query_links."""
    pass


# ---------------------------------------------------------------------------
# Slice tools — specs
# ---------------------------------------------------------------------------

class ComponentSpec(BaseModel):
    """Component specification for nodes."""
    model: str = Field(..., description="Component model (e.g. GPU_TeslaT4, NIC_ConnectX_6)")
    name: Optional[str] = Field(None, description="Component name (auto-generated if omitted)")


class InterfaceSpec(BaseModel):
    """Detailed interface specification for SmartNIC port control."""
    node: str = Field(..., description="Node name")
    nic: Optional[str] = Field(None, description="NIC component name (reuse or create)")
    port: int = Field(0, ge=0, description="Interface/port index (0 or 1 for SmartNICs)")
    nic_model: Optional[str] = Field(None, description="NIC model for this interface")


class NodeSpec(BaseModel):
    """Node specification for build-slice and modify-slice."""
    name: str = Field(..., min_length=1, description="Unique node name")
    site: Optional[str] = Field(None, description="FABRIC site (auto-selected if omitted)")
    cores: int = Field(2, ge=1, description="CPU cores (default 2)")
    ram: int = Field(8, ge=1, description="RAM in GB (default 8)")
    disk: int = Field(10, ge=1, description="Disk in GB (default 10)")
    image: str = Field("default_rocky_8", description="OS image")
    components: List[ComponentSpec] = Field(default_factory=list, description="Components to add")


class NetworkSpec(BaseModel):
    """Network specification for build-slice and modify-slice."""
    name: str = Field(..., min_length=1, description="Network name")
    nodes: Optional[List[str]] = Field(None, description="Simple form: list of node names")
    interfaces: Optional[List[InterfaceSpec]] = Field(
        None, description="Detailed form for SmartNIC port control"
    )
    type: Optional[str] = Field(None, description="Network type (L2PTP, L2Bridge, FABNetv4, etc.)")
    bandwidth: Optional[int] = Field(None, ge=1, description="Bandwidth in Gbps (L2PTP only)")
    nic: Optional[str] = Field(None, description="Explicit NIC model override")
    subnet: Optional[str] = Field(None, description="IPv4 subnet for L2 networks (modify only)")


class RemoveComponentSpec(BaseModel):
    """Specification for removing a component from a node."""
    node: str = Field(..., description="Node name containing the component")
    name: str = Field(..., description="Component name to remove")


class AddComponentSpec(BaseModel):
    """Specification for adding a component to an existing node."""
    node: str = Field(..., description="Node name to add component to")
    model: str = Field(..., description="Component model")
    name: Optional[str] = Field(None, description="Component name (auto-generated if omitted)")


# ---------------------------------------------------------------------------
# Slice tools — inputs
# ---------------------------------------------------------------------------

class BuildSliceInput(BaseModel):
    """Input for fabric_build_slice."""
    name: str = Field(..., min_length=1, description="Slice name")
    ssh_keys: Union[str, List[str]] = Field(..., description="SSH public keys for access")
    nodes: Union[str, List[Dict[str, Any]]] = Field(..., description="Node specifications")
    networks: Optional[Union[str, List[Dict[str, Any]]]] = Field(
        None, description="Network specifications"
    )
    lifetime: Optional[int] = Field(None, ge=1, description="Slice lifetime in days")
    lease_start_time: Optional[str] = Field(None, description="Lease start time (UTC)")
    lease_end_time: Optional[str] = Field(None, description="Lease end time (UTC)")


class QuerySlicesInput(BaseModel):
    """Input for fabric_query_slices."""
    slice_id: Optional[str] = Field(None, description="Slice GUID")
    slice_name: Optional[str] = Field(None, description="Slice name")
    slice_state: Optional[Union[str, List[str]]] = Field(
        None,
        description=(
            "Slice states to include. "
            "Values: Nascent, Configuring, StableOK, StableError, ModifyOK, ModifyError, Closing, Dead"
        ),
    )
    exclude_slice_state: Optional[Union[str, List[str]]] = Field(
        None, description="Slice states to exclude"
    )
    as_self: bool = Field(True, description="If True, list only user's own slices")
    offset: int = Field(0, ge=0, description="Pagination offset")
    limit: int = Field(200, ge=1, le=5000, description="Maximum slices to return")
    fetch_all: bool = Field(True, description="If True, automatically fetch all pages")


class GetSliversInput(BaseModel):
    """Input for fabric_get_slivers."""
    slice_id: str = Field(..., description="UUID of the slice")
    as_self: bool = Field(True, description="If True, list as owner")


class RenewSliceInput(BaseModel):
    """Input for fabric_renew_slice."""
    slice_id: str = Field(..., description="UUID of the slice to renew")
    lease_end_time: str = Field(..., description="New lease end time (UTC format)")


class DeleteSliceInput(BaseModel):
    """Input for fabric_delete_slice."""
    slice_id: str = Field(..., description="UUID of the slice to delete")


class ModifySliceInput(BaseModel):
    """Input for fabric_modify_slice."""
    slice_name: Optional[str] = Field(None, description="Slice name")
    slice_id: Optional[str] = Field(None, description="Slice UUID")
    add_nodes: Optional[List[Dict[str, Any]]] = Field(None, description="New nodes to add")
    add_components: Optional[List[Dict[str, Any]]] = Field(
        None, description="Components to add to existing nodes"
    )
    add_networks: Optional[List[Dict[str, Any]]] = Field(None, description="Networks to add")
    remove_nodes: Optional[List[str]] = Field(None, description="Node names to remove")
    remove_components: Optional[List[Dict[str, str]]] = Field(
        None, description="Components to remove: [{node, name}]"
    )
    remove_networks: Optional[List[str]] = Field(None, description="Network names to remove")


class AcceptModifyInput(BaseModel):
    """Input for fabric_accept_modify."""
    slice_id: str = Field(..., description="UUID of the slice with pending modifications")


# ---------------------------------------------------------------------------
# Network tools
# ---------------------------------------------------------------------------

class MakeIpPublicInput(BaseModel):
    """Input for fabric_make_ip_routable."""
    network_name: str = Field(..., description="FABNetv4Ext or FABNetv6Ext network name")
    slice_name: Optional[str] = Field(None, description="Slice name")
    slice_id: Optional[str] = Field(None, description="Slice UUID")
    ipv4: Optional[Union[str, List[str]]] = Field(None, description="IPv4 address(es)")
    ipv6: Optional[Union[str, List[str]]] = Field(None, description="IPv6 address(es)")


class GetNetworkInfoInput(BaseModel):
    """Input for fabric_get_network_info."""
    network_name: str = Field(..., description="Network name")
    slice_name: Optional[str] = Field(None, description="Slice name")
    slice_id: Optional[str] = Field(None, description="Slice UUID")


# ---------------------------------------------------------------------------
# Project / user tools
# ---------------------------------------------------------------------------

class ShowProjectsInput(BaseModel):
    """Input for fabric_show_projects."""
    project_name: str = Field("all", description="Project name filter")
    project_id: str = Field("all", description="Project id filter")
    uuid: Optional[str] = Field(None, description="User UUID")
    sort: Optional[Dict[str, Any]] = Field(None, description="Sort specification")
    limit: Optional[int] = Field(200, ge=1, le=5000, description="Maximum results")
    offset: int = Field(0, ge=0, description="Results to skip")


class ListProjectUsersInput(BaseModel):
    """Input for fabric_list_project_users."""
    project_uuid: str = Field(..., min_length=1, description="Project UUID (required)")
    sort: Optional[Dict[str, Any]] = Field(None, description="Sort specification")
    limit: Optional[int] = Field(200, ge=1, le=5000, description="Maximum results")
    offset: int = Field(0, ge=0, description="Results to skip")


class GetUserKeysInput(BaseModel):
    """Input for fabric_get_user_keys."""
    user_uuid: Optional[str] = Field(None, description="User UUID (person_uuid)")
    key_type: str = Field("sliver", description='Key type filter (e.g. "sliver", "bastion")')


class GetBastionUsernameInput(BaseModel):
    """Input for fabric_get_bastion_username."""
    user_uuid: Optional[str] = Field(None, description="User UUID (person_uuid)")


class GetUserInfoInput(BaseModel):
    """Input for fabric_get_user_info."""
    self_info: bool = Field(True, description="If True, fetch info for the authenticated user")
    user_uuid: Optional[str] = Field(
        None, description="User UUID (required when self_info=False)"
    )


class AddPublicKeyInput(BaseModel):
    """Input for fabric_add_public_key."""
    sliver_id: str = Field(..., min_length=1, description="NodeSliver UUID")
    sliver_key_name: Optional[str] = Field(None, description="Portal key comment name")
    email: Optional[str] = Field(None, description="User email")
    sliver_public_key: Optional[str] = Field(
        None, description='Full public key string, e.g. "ecdsa-sha2-nistp256 AAAA..."'
    )


class RemovePublicKeyInput(BaseModel):
    """Input for fabric_remove_public_key."""
    sliver_id: str = Field(..., min_length=1, description="NodeSliver UUID")
    sliver_key_name: Optional[str] = Field(None, description="Portal key comment name")
    email: Optional[str] = Field(None, description="User email")
    sliver_public_key: Optional[str] = Field(
        None, description='Full public key string, e.g. "ecdsa-sha2-nistp256 AAAA..."'
    )


class OsRebootInput(BaseModel):
    """Input for fabric_os_reboot."""
    sliver_id: str = Field(..., min_length=1, description="NodeSliver UUID")
