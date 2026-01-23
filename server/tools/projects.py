"""
Project info tools for FABRIC MCP Server.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from server.dependencies.fabric_manager import get_fabric_manager
from server.log_helper.decorators import tool_logger
from server.utils.async_helpers import call_threadsafe
from server.utils.data_helpers import apply_sort, paginate


@tool_logger("show-my-projects")
async def show_my_projects(
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    project_name: str = "all",
    project_id: str = "all",
    uuid: Optional[str] = None,
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    Show Core API project info for the current user (or specified uuid).

    Args:
        project_name: Project name filter (default "all").
        project_id: Project id filter (default "all").
        uuid: Optional user UUID; Core API infers current user if omitted.
        sort: Sort specification {"field": "<field>", "direction": "asc|desc"}.
        limit: Maximum results (default 200).
        offset: Number of results to skip (default 0).

    Returns:
        List of project records.
    """
    fm, id_token = get_fabric_manager()
    items = await call_threadsafe(
        fm.get_project_info,
        id_token=id_token,
        project_name=project_name,
        project_id=project_id,
        uuid=uuid,
    )
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


TOOLS = [show_my_projects]


@tool_logger("list-project-users")
async def list_project_users(
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    project_uuid: str = "",
    sort: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    List users in a project.

    Args:
        project_uuid: Project UUID (required).
        sort: Sort specification {"field": "<field>", "direction": "asc|desc"}.
        limit: Max results (default 200).
        offset: Results to skip (default 0).

    Returns:
        List of user records.
    """
    if not project_uuid:
        raise ValueError("project_uuid is required")

    fm, id_token = get_fabric_manager()
    items = await call_threadsafe(
        fm.list_project_users,
        id_token=id_token,
        project_uuid=project_uuid,
    )
    items = apply_sort(items, sort)
    return paginate(items, limit=limit, offset=offset)


TOOLS.append(list_project_users)


@tool_logger("get-user-keys")
async def get_user_keys(
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    user_uuid: str = "",
    key_type: Optional[str] = "sliver",
) -> List[Dict[str, Any]]:
    """
    Fetch SSH/public keys for a specific user (person_uuid).

    Args:
        user_uuid: User UUID (person_uuid) required.
        key_type: Optional key type filter (e.g., \"sliver\", \"bastion\"); default \"sliver\".

    Returns:
        List of key records.
    """
    if not user_uuid:
        raise ValueError("user_uuid is required")

    fm, id_token = get_fabric_manager()
    items = await call_threadsafe(
        fm.get_user_keys,
        id_token=id_token,
        user_uuid=user_uuid,
        key_type_filter=key_type,
    )
    return items


TOOLS.append(get_user_keys)

@tool_logger("add-public-key")
async def add_public_key(
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    sliver_id: str = "",
    sliver_key_name: Optional[str] = None,
    email: Optional[str] = None,
    sliver_public_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Add a public key to a NodeSliver via POA addkey. Provide either sliver_key_name (portal comment) or sliver_public_key.
    sliver_public_key must include key type, e.g., "ecdsa-sha2-nistp256 AAAA...==".
    """
    if not sliver_id:
        raise ValueError("sliver_id is required")
    if not sliver_key_name and not sliver_public_key:
        raise ValueError("sliver_key_name or sliver_public_key is required")

    fm, id_token = get_fabric_manager()
    res = await call_threadsafe(
        fm.add_public_key,
        id_token=id_token,
        sliver_id=sliver_id,
        sliver_key_name=sliver_key_name,
        email=email,
        sliver_public_key=sliver_public_key,
    )
    return res if isinstance(res, list) else [res]


@tool_logger("remove-public-key")
async def remove_public_key(
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    sliver_id: str = "",
    sliver_key_name: Optional[str] = None,
    email: Optional[str] = None,
    sliver_public_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Remove a public key from a NodeSliver via POA removekey. Provide either sliver_key_name (portal comment) or sliver_public_key.
    sliver_public_key must include key type, e.g., "ecdsa-sha2-nistp256 AAAA...==".
    """
    if not sliver_id:
        raise ValueError("sliver_id is required")
    if not sliver_key_name and not sliver_public_key:
        raise ValueError("sliver_key_name or sliver_public_key is required")

    fm, id_token = get_fabric_manager()
    res = await call_threadsafe(
        fm.remove_public_key,
        id_token=id_token,
        sliver_id=sliver_id,
        sliver_key_name=sliver_key_name,
        email=email,
        sliver_public_key=sliver_public_key,
    )
    return res if isinstance(res, list) else [res]


TOOLS.extend([add_public_key, remove_public_key])


@tool_logger("os-reboot")
async def os_reboot(
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    sliver_id: str = "",
) -> List[Dict[str, Any]]:
    """
    Reboot a sliver via POA.
    """
    if not sliver_id:
        raise ValueError("sliver_id is required")

    fm, id_token = get_fabric_manager()
    res = await call_threadsafe(
        fm.os_reboot,
        id_token=id_token,
        sliver_id=sliver_id,
    )
    return res if isinstance(res, list) else [res]


TOOLS.append(os_reboot)
