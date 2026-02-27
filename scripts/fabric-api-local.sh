#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# fabric-api-local.sh — Run FABRIC MCP server in local/stdio mode
#
# Runs the MCP server locally, reading credentials from fabric_rc.
# Supports all tools including post-boot VM configuration via SSH.
#
# Prerequisite: pip install fabric_api_mcp into your venv
# ---------------------------------------------------------------

# ===================== USER CONFIGURATION =====================
# Update these defaults to match your environment, or override
# at runtime via env vars (e.g., FABRIC_RC=~/my/fabric_rc ./fabric-api-local.sh)

# Path to your fabric_rc file
FABRIC_RC="${FABRIC_RC:-$HOME/work/fabric_config/fabric_rc}"

# Path to your Python virtual environment (with fabric_api_mcp installed)
FABRIC_VENV="${FABRIC_VENV:-$HOME/work/fabric-api-mcp/venv}"

# ==============================================================

# --- Source fabric_rc if not already sourced ---
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

# --- Activate venv ---
if [[ -d "$FABRIC_VENV" ]]; then
  # shellcheck source=/dev/null
  source "$FABRIC_VENV/bin/activate"
else
  echo "[!] Python venv not found at $FABRIC_VENV" >&2
  echo "    Set FABRIC_VENV to the path of your virtual environment." >&2
  exit 1
fi

# --- Enable local mode and run ---
export FABRIC_LOCAL_MODE=1
exec python3 -m fabric_api_mcp
