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
    user_uuid: Optional[str] = None,
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
    fm, id_token = get_fabric_manager()
    items = await call_threadsafe(
        fm.get_user_keys,
        id_token=id_token,
        user_uuid=user_uuid,
        key_type_filter=key_type,
    )
    return items


TOOLS.append(get_user_keys)

@tool_logger("get-bastion-username")
async def get_bastion_username(
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    user_uuid: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch bastion username for a specific user (person_uuid).

    Args:
        user_uuid: User UUID (person_uuid) required.

    Returns:
        List of key records.
    """
    fm, id_token = get_fabric_manager()
    user_info = await call_threadsafe(
        fm.get_user_info,
        id_token=id_token,
        user_uuid=user_uuid,
    )
    return user_info.get("bastion_login")


TOOLS.append(get_bastion_username)

@tool_logger("get-user-info")
async def get_user_info(
    toolCallId: Optional[str] = None,
    tool_call_id: Optional[str] = None,
    self_info: bool = True,
    user_uuid: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch detailed user information from the FABRIC Core API.

    Args:
        self_info: If True (default), fetch info for the authenticated user (token owner).
            Set to False and provide user_uuid to fetch info for another user.
        user_uuid: User UUID (person_uuid) to fetch info for another user.
            Only used when self_info=False.

    Returns:
        Dict containing user details including:
        - uuid: User's unique identifier
        - name: Display name
        - email: Primary email address
        - affiliation: Organization/institution
        - bastion_login: Username for bastion host SSH access
        - fabric_id: FABRIC identifier (e.g., "FABRIC1000015")
        - eppn: eduPersonPrincipalName
        - registered_on: Registration timestamp
        - roles: List of project roles (project-owner, project-member, etc.)
        - sshkeys: List of registered SSH keys with fingerprints and expiry
        - profile: Bio, job title, pronouns, website, etc.
        - preferences: Privacy settings for profile visibility

    Example - fetch your own info (self_info=True, default):
        get-user-info()
        # or explicitly: get-user-info(self_info=True)

    Example - fetch another user's info:
        get-user-info(self_info=False, user_uuid="43b7271b-90eb-45f6-833a-e51cf13bbc68")

    Example response:
        {
          "results": [{
            "uuid": "43b7271b-90eb-45f6-833a-e51cf13bbc68",
            "name": "Komal Thareja",
            "email": "kthare10@email.unc.edu",
            "affiliation": "University of North Carolina at Chapel Hill",
            "bastion_login": "kthare10_0011904101",
            "fabric_id": "FABRIC1000015",
            "roles": [
              {"name": "990d8a8b-...-pm", "description": "FABRIC Staff"},
              ...
            ],
            "sshkeys": [
              {"fingerprint": "MD5:f5:fd:...", "ssh_key_type": "ecdsa-sha2-nistp256", ...}
            ],
            "profile": {"bio": "...", "job": "Sr Distributed Systems Software Engineer", ...}
          }],
          "size": 1,
          "status": 200
        }
    """
    fm, id_token = get_fabric_manager()

    # Determine which user to fetch
    target_uuid = None if self_info else user_uuid
    if not self_info and not user_uuid:
        raise ValueError("user_uuid is required when self_info=False")

    user_info = await call_threadsafe(
        fm.get_user_info,
        id_token=id_token,
        user_uuid=target_uuid,
    )
    return user_info


TOOLS.append(get_user_info)

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
