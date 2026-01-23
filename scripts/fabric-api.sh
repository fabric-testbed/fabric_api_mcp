#!/usr/bin/env bash
set -euo pipefail

# --- Config (override via env) ---
TOKEN_JSON="${FABRIC_TOKEN_JSON:-$HOME/work/claude/id_token.json}"     # JSON with {"id_token": "..."}
REMOTE_URL="${FABRIC_MCP_URL:-https://alpha-5.fabric-testbed.net/mcp}"

# --- Read token (requires jq) ---
if ! command -v jq >/dev/null 2>&1; then
  echo "[!] jq is required (brew install jq)" >&2
  exit 1
fi
ID_TOKEN="$(jq -r '.id_token' "$TOKEN_JSON")"
if [[ -z "${ID_TOKEN}" || "${ID_TOKEN}" == "null" ]]; then
  echo "[!] Could not read .id_token from: $TOKEN_JSON" >&2
  exit 1
fi

# --- Launch mcp-remote with header + system prompt ---
# Note: This relies on mcp-remote supporting --system.
# If your version doesn't, see the notes below for alternatives.
exec npx mcp-remote \
  "$REMOTE_URL" \
  --header "Authorization: Bearer ${ID_TOKEN}" 
