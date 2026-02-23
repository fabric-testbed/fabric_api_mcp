"""
Shared FablibManagerV2 factory for slice builder / modifier / network tools.
"""
from __future__ import annotations

from fabrictestbed_extensions.fablib.fablib import FablibManager

from server.config import config


def create_fablib_manager(id_token: str) -> FablibManager:
    """Create a FablibManagerV2 instance with the given id_token."""
    return FablibManager(
        id_token=id_token,
        credmgr_host=config.credmgr_host,
        orchestrator_host=config.orchestrator_host,
        core_api_host=config.core_api_host,
        am_host=config.am_host,
        auto_token_refresh=False,
        validate_config=False,
        log_level=config.log_level,
        log_path=True,
    )
