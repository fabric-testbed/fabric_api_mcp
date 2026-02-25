#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# fabric-api-local.sh — Run FABRIC MCP server in local/stdio mode
#
# Prerequisites:
#   1. A fabric_rc file that exports FABRIC_TOKEN_LOCATION,
#      FABRIC_ORCHESTRATOR_HOST, FABRIC_CREDMGR_HOST, etc.
#   2. A Python environment with the server's dependencies installed
#      (see server/requirements.txt).
#
# Usage (standalone):
#   source ~/work/fabric_config/fabric_rc
#   ./scripts/fabric-api-local.sh
#
# Usage (Claude Desktop — claude_desktop_config.json):
#   {
#     "mcpServers": {
#       "fabric-api": {
#         "command": "/path/to/fabric_api_mcp/scripts/fabric-api-local.sh"
#       }
#     }
#   }
#
# Override defaults with env vars:
#   FABRIC_RC        — path to fabric_rc (default: ~/work/fabric_config/fabric_rc)
#   FABRIC_MCP_DIR   — path to fabric_api_mcp checkout (auto-detected from script location)
#   FABRIC_VENV      — path to Python venv (default: $FABRIC_MCP_DIR/.venv)
# ---------------------------------------------------------------

# --- Resolve project directory ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FABRIC_MCP_DIR="${FABRIC_MCP_DIR:-$(dirname "$SCRIPT_DIR")}"

# --- Source fabric_rc if not already sourced ---
FABRIC_RC="${FABRIC_RC:-$HOME/work/fabric_config/fabric_rc}"
if [[ -z "${FABRIC_TOKEN_LOCATION:-}" ]]; then
  if [[ -f "$FABRIC_RC" ]]; then
    # shellcheck source=/dev/null
    source "$FABRIC_RC"
  else
    echo "[!] fabric_rc not found at $FABRIC_RC and FABRIC_TOKEN_LOCATION is not set." >&2
    echo "    Set FABRIC_RC or source your fabric_rc before running this script." >&2
    exit 1
  fi
fi

# --- Activate venv if present ---
FABRIC_VENV="${FABRIC_VENV:-$FABRIC_MCP_DIR/.venv}"
if [[ -d "$FABRIC_VENV" ]]; then
  # shellcheck source=/dev/null
  source "$FABRIC_VENV/bin/activate"
fi

# --- Enable local mode ---
export FABRIC_LOCAL_MODE=1

# --- Run the MCP server (stdio transport) ---
cd "$FABRIC_MCP_DIR"
exec python3 -m server
