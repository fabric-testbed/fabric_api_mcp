"""
Shared FablibManagerV2 factory for slice builder / modifier / network tools.
"""
from __future__ import annotations

from fabrictestbed_extensions.fablib.fablib import FablibManager

from fabric_api_mcp.config import config


def create_fablib_manager(id_token: str = None) -> FablibManager:
    """Create a FablibManagerV2 instance.

    In local mode the token, hosts, and SSH settings are sourced from
    environment variables (e.g. FABRIC_TOKEN_LOCATION) so *id_token* is
    ignored.  In server mode the explicit *id_token* is required.
    """
    if config.local_mode:
        return FablibManager(
            fabric_rc=config.fabric_rc,
            auto_token_refresh=True,
            validate_config=False,
            no_ssh=False,
            log_level=config.log_level,
            log_path=True,
        )

    if not id_token:
        raise ValueError("Authentication Required: Missing or invalid Authorization Bearer token.")

    return FablibManager(
        id_token=id_token,
        credmgr_host=config.credmgr_host,
        orchestrator_host=config.orchestrator_host,
        core_api_host=config.core_api_host,
        am_host=config.am_host,
        auto_token_refresh=False,
        validate_config=False,
        no_ssh=True,
        log_level=config.log_level,
        log_path=True,
    )
