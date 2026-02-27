#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# fabric-api.sh — Connect to a remote FABRIC MCP server
#
# Uses mcp-remote to bridge stdio to a Docker Compose-deployed
# MCP server over HTTPS, sending a Bearer token with each request.
#
# Prerequisites: jq, npx (Node.js)
# ---------------------------------------------------------------

# ===================== USER CONFIGURATION =====================
# Update these defaults to match your environment, or override
# at runtime via env vars (e.g., FABRIC_TOKEN_JSON=~/my/token.json ./fabric-api.sh)

# Path to your FABRIC token JSON file (must contain {"id_token": "..."})
# Download from: FABRIC Portal → Experiments → Manage Tokens
FABRIC_TOKEN_JSON="${FABRIC_TOKEN_JSON:-$HOME/work/fabric-api-mcp/id_token.json}"

# URL of the remote MCP server (Docker Compose-deployed)
FABRIC_MCP_URL="${FABRIC_MCP_URL:-https://alpha-5.fabric-testbed.net/mcp}"

# ==============================================================

# --- Validate prerequisites ---
if ! command -v jq >/dev/null 2>&1; then
  echo "[!] jq is required (brew install jq / apt install jq)" >&2
  exit 1
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "[!] npx is required (brew install node / apt install nodejs npm)" >&2
  exit 1
fi

# --- Read token ---
if [[ ! -f "$FABRIC_TOKEN_JSON" ]]; then
  echo "[!] Token file not found: $FABRIC_TOKEN_JSON" >&2
  echo "    Set FABRIC_TOKEN_JSON or place your token at the default path." >&2
  exit 1
fi

ID_TOKEN="$(jq -r '.id_token' "$FABRIC_TOKEN_JSON")"
if [[ -z "${ID_TOKEN}" || "${ID_TOKEN}" == "null" ]]; then
  echo "[!] Could not read .id_token from: $FABRIC_TOKEN_JSON" >&2
  exit 1
fi

# --- Launch mcp-remote ---
exec npx mcp-remote \
  "$FABRIC_MCP_URL" \
  --header "Authorization: Bearer ${ID_TOKEN}"
