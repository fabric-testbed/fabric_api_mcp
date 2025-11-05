from __future__ import annotations

import os
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, List

from fabric_cf.orchestrator.orchestrator_proxy import Status
from fabrictestbed.util.constants import Constants
from fastmcp import FastMCP
from fastmcp.server.context import Context
from fastmcp.server.dependencies import get_http_headers

from fabrictestbed.fabric_manager import FabricManager
from fim.user import GraphFormat
from numpy.f2py.cfuncs import includes

# ---------------------------------------
# Config
# ---------------------------------------
FABRIC_ORCHESTRATOR_HOST = os.environ.get(Constants.FABRIC_ORCHESTRATOR_HOST,
                                          "orchestrator.fabric-testbed.net")

print(f"Orchestrator HOST: {FABRIC_ORCHESTRATOR_HOST}")

FABRIC_AM_HOST = os.environ.get(Constants.FABRIC_AM_HOST,
                                          "artifacts.fabric-testbed.net")

print(f"Artifact Manager HOST: {FABRIC_AM_HOST}")

FABRIC_CORE_API_HOST = os.environ.get(Constants.FABRIC_CORE_API_HOST,
                                          "uis.fabric-testbed.net")

print(f"Core Api HOST: {FABRIC_CORE_API_HOST}")

FABRIC_CREDMGR_HOST = os.environ.get(Constants.FABRIC_CREDMGR_HOST,
                                          "cm.fabric-testbed.net")

print(f"Credmgr HOST: {FABRIC_CREDMGR_HOST}")


# Meta fields various bridges may attach to tool calls
EXTRA_META_ARGS = [
    "toolCallId",  # camelCase
    "tool_call_id",  # snake_case
    "id",  # "call_tool" envelope
    "type",  # "call_tool" envelope
    "name",  # envelope alt for tool name
    "tool",  # if a wrapper redundantly includes it
]

mcp = FastMCP(
    name="fabric-mcp-proxy",
    instructions="Proxy for accessing FABRIC API data via LLM tool calls.",
    version="1.3.0",
)

# Load your markdown system prompt
SYSTEM_TEXT = Path("prompts/system.md").read_text(encoding="utf-8").strip()

# Define a function to load the prompt content
# The docstring becomes the prompt's description.
@mcp.prompt(name="fabric-system")
def fabric_system_prompt():
    """System rules for querying FABRIC via MCP"""
    # FastMCP automatically wraps the string as a PromptMessage with role="system"
    # if you return it from the function. You could also return a list of PromptMessage objects.
    return SYSTEM_TEXT

# Note: The function name (or the name parameter) is the key.
# The docstring is the description.
# The return value is the prompt content/messages.

# ---------------------------------------
# Helpers
# ---------------------------------------
def _bearer_from_headers(headers: Dict[str, str]) -> Optional[str]:
    low = {k.lower(): v for k, v in headers.items()}
    auth = low.get("authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _client_from_headers() -> FabricManager:
    headers = get_http_headers() or {}
    token = _bearer_from_headers(headers)
    if not token:
        raise ValueError("Authentication Required: Missing or invalid Authorization Bearer token.")
    return FabricManager(cm_host=FABRIC_CREDMGR_HOST,
                         oc_host=FABRIC_ORCHESTRATOR_HOST,
                         core_api_host=FABRIC_CORE_API_HOST,
                         am_host=FABRIC_AM_HOST,
                         id_token=token,
                         no_write=True)


async def _call(client: FabricManager, method: str, **kwargs) -> Dict[str, Any]:
    """
    Call a FablibManager method in a thread, filtering out None args.
    """
    fn = getattr(client, method)
    final_args = {k: v for k, v in kwargs.items() if v is not None}
    return await asyncio.to_thread(fn, **final_args)


# ---------------------------------------
# Slices
# ---------------------------------------
@mcp.tool(
    name="query-slices",
    title="Query Slices",
    description="Query slices with rich filters. Lists accept multiple values.",

)
async def query_slices(
        ctx: Context, toolCallId: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        as_self: bool = True,
        slice_id: Optional[str] = None,
        slice_name: Optional[str] = None,
        slice_state: Optional[List[str]] = None,
        exclude_slice_state: Optional[List[str]] = None,
        offset: int = 0,
        limit: int = 1000,
        fetch_all: bool = True,
        graph_format: Optional[str] = str(GraphFormat.GRAPHML)
) -> Dict[str, Any]:
    client = _client_from_headers()
    status, result = await _call(
        client, "slices",
        as_self=as_self,
        slice_id=slice_id,
        name=slice_name,
        includes=slice_state,
        excludes=exclude_slice_state,
        graph_format=graph_format,
        offset=offset,
        limit=limit,
        fetch_all=fetch_all,
    )
    if status != Status.OK:
        raise Exception(result)
    slices = {}
    for s in result:
        slices[s.name] = s.to_dict()


# ---------------------------------------
# Run
# ---------------------------------------
if __name__ == "__main__":
    import os

    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"Starting FABRIC MCP (FastMCP) on http://{host}:{port}")
    mcp.run(transport="http", host=host, port=port)