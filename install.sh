#!/usr/bin/env bash
set -euo pipefail

# ===================================================================
# install.sh — One-liner installer for FABRIC API MCP
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/install.sh | bash -s -- --local
#   curl -fsSL https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/install.sh | bash -s -- --remote
#   curl -fsSL https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/install.sh | bash -s -- --local --remote
# ===================================================================

WORK_DIR="$HOME/work"
INSTALL_DIR="$WORK_DIR/fabric-api-mcp"
BIN_DIR="$INSTALL_DIR/bin"
VENV_DIR=""
CONFIG_DIR=""
INSTALL_LOCAL=false
INSTALL_REMOTE=false
NO_BROWSER=false
CONFIGURED_PROJECT_ID=""

GITHUB_RAW="https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main"

# ----------------------- Shared bootstrap helpers -----------------------
#
# Logging, OS and package-manager detection, package installation, Python
# discovery and venv creation are identical across FABRIC MCP servers, so they
# live in fabric_mcp_common instead of being copied into each install.sh.
#
# This runs before any virtualenv exists, so the library cannot be imported from
# the Python package — it is fetched over HTTPS. Point
# FABRIC_MCP_COMMON_INSTALL_SH at a local file to use a checkout instead (offline
# installs, or testing an unreleased change).

FMC_RAW="${FABRIC_MCP_COMMON_RAW:-https://raw.githubusercontent.com/fabric-testbed/fabric-mcp-common/main}"
FMC_INSTALL_SH="${FABRIC_MCP_COMMON_INSTALL_SH:-}"
FMC_TMP=""

# Cannot use err()/die() yet — they are defined by the file being fetched.
_bootstrap_die() { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

if [[ -z "$FMC_INSTALL_SH" ]]; then
  FMC_TMP="$(mktemp -t fabric-mcp-install-common.XXXXXX)" \
    || _bootstrap_die "Could not create a temporary file for installer helpers."
  FMC_URL="$FMC_RAW/fabric_mcp_common/templates/install-common.sh"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$FMC_URL" -o "$FMC_TMP" \
      || _bootstrap_die "Could not download installer helpers from $FMC_URL"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$FMC_TMP" "$FMC_URL" \
      || _bootstrap_die "Could not download installer helpers from $FMC_URL"
  else
    _bootstrap_die "Neither curl nor wget is available; install one and re-run."
  fi
  FMC_INSTALL_SH="$FMC_TMP"
fi

[[ -s "$FMC_INSTALL_SH" ]] \
  || _bootstrap_die "Installer helpers missing or empty: $FMC_INSTALL_SH"

# shellcheck source=/dev/null
source "$FMC_INSTALL_SH" \
  || _bootstrap_die "Could not load installer helpers from $FMC_INSTALL_SH"
[[ -n "$FMC_TMP" ]] && rm -f "$FMC_TMP"

# Sanity-check the contract, so a drifted upstream fails here with a clear
# message rather than as "command not found" halfway through an install.
for _fn in info ok warn err die detect_os ensure_command ensure_python ensure_venv; do
  declare -F "$_fn" >/dev/null \
    || _bootstrap_die "Installer helpers did not define '$_fn' — version mismatch?"
done
unset _fn

usage() {
  cat <<'EOF'
Usage: install.sh [OPTIONS]

Options:
  --local              Set up local mode (stdio transport, SSH to VMs, post-boot config)
  --remote             Set up remote mode (connects to remote MCP server via mcp-remote)
  --config-dir <path>  Override FABRIC config directory (default: ~/work/fabric_config)
  --venv <path>        Override Python venv path (default: ~/work/fabric-api-mcp/venv)
  --no-browser         Pass --no-browser to fabric-cli (for headless environments)
  --help               Show this help message

Both modes install a Python venv with fabric_api_mcp and fabric-cli.
Remote mode additionally requires jq + Node.js (npx/mcp-remote).

Examples:
  # Local mode (full-featured)
  bash install.sh --local

  # Remote mode (lightweight)
  bash install.sh --remote

  # Both modes
  bash install.sh --local --remote

  # Headless environment
  bash install.sh --local --no-browser
EOF
  exit 0
}

# ----------------------- Argument parsing -----------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local)       INSTALL_LOCAL=true; shift ;;
    --remote)      INSTALL_REMOTE=true; shift ;;
    --config-dir)  CONFIG_DIR="$2"; shift 2 ;;
    --venv)        VENV_DIR="$2"; shift 2 ;;
    --no-browser)  NO_BROWSER=true; shift ;;
    --help|-h)     usage ;;
    *)             die "Unknown option: $1 (use --help for usage)" ;;
  esac
done

if ! $INSTALL_LOCAL && ! $INSTALL_REMOTE; then
  die "Specify at least one mode: --local and/or --remote (use --help for usage)"
fi

# Apply defaults after arg parsing
VENV_DIR="${VENV_DIR:-$INSTALL_DIR/venv}"
CONFIG_DIR="${CONFIG_DIR:-$WORK_DIR/fabric_config}"

# ----------------------- Common setup -----------------------

setup_dirs() {
  info "Creating directories: $WORK_DIR, $INSTALL_DIR"
  mkdir -p "$WORK_DIR"
  mkdir -p "$BIN_DIR"
  ok "Directories created"
}

setup_venv() {
  info "=== Setting up Python venv + fabric_api_mcp ==="

  # 1. Ensure Python 3.11+, then create the venv and upgrade pip inside it
  ensure_python
  ensure_venv "$VENV_DIR"

  # 2. Install fabric_api_mcp into venv (includes fabric-cli as dependency)
  info "Installing fabric_api_mcp into venv..."
  # The install below is pip-from-git, so git must be present. Dependencies
  # (including fabric_mcp_common) resolve from PyPI via pyproject.toml.
  ensure_command git
  "$VENV_DIR/bin/pip" install --quiet "git+https://github.com/fabric-testbed/fabric_api_mcp.git"
  ok "fabric_api_mcp installed (includes fabric-cli)"
}

setup_configure() {
  # Create config dir
  mkdir -p "$CONFIG_DIR"
  ok "Config directory: $CONFIG_DIR"

  # Run fabric-cli configure setup (interactive) — use the venv's fabric-cli
  local venv_cli="$VENV_DIR/bin/fabric-cli"
  if [[ -f "$CONFIG_DIR/fabric_rc" ]]; then
    ok "fabric_rc already exists at $CONFIG_DIR/fabric_rc — skipping configure"
  else
    if [[ -x "$venv_cli" ]]; then
      info "Running fabric-cli configure setup..."
      info "This will open a browser for CILogon authentication."
      info "If not specified, your first FABRIC project will be selected by default."
      local cli_args=(configure setup --config-dir "$CONFIG_DIR")
      if $NO_BROWSER; then
        cli_args+=(--no-browser)
      fi
      "$venv_cli" "${cli_args[@]}" || {
        warn "fabric-cli configure setup failed or was cancelled."
        warn "You can run it later: $venv_cli configure setup --config-dir $CONFIG_DIR"
      }
    else
      warn "fabric-cli not found in venv. Run manually after install:"
      warn "  $venv_cli configure setup --config-dir $CONFIG_DIR"
    fi
  fi

  # Extract project ID from fabric_rc (if it exists)
  if [[ -f "$CONFIG_DIR/fabric_rc" ]]; then
    CONFIGURED_PROJECT_ID="$(sed -n 's/^export FABRIC_PROJECT_ID=//p' "$CONFIG_DIR/fabric_rc" 2>/dev/null || true)"
  fi
}

# ----------------------- Local mode setup -----------------------

setup_local() {
  info "=== Setting up LOCAL mode ==="

  # Download fabric-api-local.sh
  info "Downloading fabric-api-local.sh..."
  curl -fsSL "$GITHUB_RAW/scripts/fabric-api-local.sh" -o "$BIN_DIR/fabric-api-local.sh"
  chmod +x "$BIN_DIR/fabric-api-local.sh"

  # Patch defaults to point to installed paths
  sed -i.bak "s|FABRIC_VENV:-\$HOME/work/fabric-api-mcp/venv|FABRIC_VENV:-$VENV_DIR|" "$BIN_DIR/fabric-api-local.sh"
  sed -i.bak "s|FABRIC_RC:-\$HOME/work/fabric_config/fabric_rc|FABRIC_RC:-$CONFIG_DIR/fabric_rc|" "$BIN_DIR/fabric-api-local.sh"
  rm -f "$BIN_DIR/fabric-api-local.sh.bak"
  ok "fabric-api-local.sh installed to $BIN_DIR/"

  ok "Local mode setup complete!"
}

# ----------------------- Remote mode setup -----------------------

setup_remote() {
  info "=== Setting up REMOTE mode ==="

  # 1. Ensure jq
  ensure_command jq

  # 2. Ensure Node.js / npx
  if command -v npx >/dev/null 2>&1; then
    ok "npx is already installed"
  else
    info "Installing Node.js..."
    case "$PKG_MGR" in
      brew) brew install node ;;
      apt)  sudo apt-get update -qq && sudo apt-get install -y -qq nodejs npm ;;
      yum)  sudo yum install -y nodejs npm ;;
      dnf)  sudo dnf install -y nodejs npm ;;
      *)    die "Cannot install Node.js. Install it manually and re-run." ;;
    esac
    if ! command -v npx >/dev/null 2>&1; then
      die "npx still not found after installing Node.js. Install Node.js manually."
    fi
    ok "Node.js installed"
  fi

  # 3. Create token via fabric-cli (available from the venv)
  local token_dir="$INSTALL_DIR"
  local token_file="$token_dir/id_token.json"
  local venv_cli="$VENV_DIR/bin/fabric-cli"
  if [[ -f "$token_file" ]]; then
    ok "Token file already exists: $token_file"
  else
    info "Creating FABRIC token via fabric-cli..."
    local cli_args=(tokens create --location "$token_file")
    if $NO_BROWSER; then
      cli_args+=(--no-browser)
    fi
    "$venv_cli" "${cli_args[@]}" || {
      warn "Token creation failed or was cancelled."
      warn "You can create a token later:"
      warn "  $venv_cli tokens create --location $token_file"
      warn "Or download from: https://portal.fabric-testbed.net/experiments#manageTokens"
    }
  fi

  # 4. Download fabric-api.sh
  info "Downloading fabric-api.sh..."
  curl -fsSL "$GITHUB_RAW/scripts/fabric-api.sh" -o "$BIN_DIR/fabric-api.sh"
  chmod +x "$BIN_DIR/fabric-api.sh"

  # Patch default token path to installed location
  sed -i.bak "s|FABRIC_TOKEN_JSON:-\$HOME/work/fabric-api-mcp/id_token.json|FABRIC_TOKEN_JSON:-$token_file|" "$BIN_DIR/fabric-api.sh"
  rm -f "$BIN_DIR/fabric-api.sh.bak"
  ok "fabric-api.sh installed to $BIN_DIR/"

  ok "Remote mode setup complete!"
}

# ----------------------- Summary -----------------------

print_summary() {
  echo ""
  echo "============================================================"
  echo "  FABRIC MCP installation complete!"
  echo "============================================================"
  echo ""
  echo "  Install directory:  $INSTALL_DIR"
  echo "  Venv:     $VENV_DIR"

  if $INSTALL_LOCAL; then
    echo "  Config:   $CONFIG_DIR"
    if [[ -n "$CONFIGURED_PROJECT_ID" ]]; then
      echo "  Project:  $CONFIGURED_PROJECT_ID"
    fi
    echo ""
    echo "  --- Local mode ---"
    echo "  Script:   $BIN_DIR/fabric-api-local.sh"
    echo ""
    echo "  MCP client config (Claude Code CLI):"
    echo "    claude mcp add fabric-api $BIN_DIR/fabric-api-local.sh"
    echo ""
    echo "  MCP client config (JSON — Claude Desktop / VS Code):"
    cat <<JSONEOF
    {
      "mcpServers": {
        "fabric-api": {
          "command": "$BIN_DIR/fabric-api-local.sh"
        }
      }
    }
JSONEOF
  fi

  if $INSTALL_REMOTE; then
    echo ""
    echo "  --- Remote mode ---"
    echo "  Script:   $BIN_DIR/fabric-api.sh"
    echo "  Token:    $INSTALL_DIR/id_token.json"
    echo ""
    echo "  MCP client config (Claude Code CLI):"
    echo "    claude mcp add fabric-api $BIN_DIR/fabric-api.sh"
    echo ""
    echo "  MCP client config (JSON — Claude Desktop / VS Code):"
    cat <<JSONEOF
    {
      "mcpServers": {
        "fabric-api": {
          "command": "$BIN_DIR/fabric-api.sh"
        }
      }
    }
JSONEOF
  fi

  echo ""
  echo "  Next steps:"
  local step=1
  if $INSTALL_LOCAL && [[ ! -f "$CONFIG_DIR/fabric_rc" ]]; then
    echo "    $step. Run: $VENV_DIR/bin/fabric-cli configure setup --config-dir $CONFIG_DIR"
    step=$((step + 1))
  fi
  echo "    $step. Add the MCP server to your client (see config above)"

  if $INSTALL_LOCAL; then
    echo ""
    echo "  To change your FABRIC project:"
    echo "    $VENV_DIR/bin/fabric-cli configure setup --config-dir $CONFIG_DIR --projectname <name>"
    echo "    $VENV_DIR/bin/fabric-cli configure setup --config-dir $CONFIG_DIR --projectid <uuid>"
  fi

  echo ""
  echo "  To refresh your token:"
  if $INSTALL_LOCAL; then
    echo "    $VENV_DIR/bin/fabric-cli tokens refresh --location $CONFIG_DIR/tokens.json"
  fi
  if $INSTALL_REMOTE; then
    echo "    $VENV_DIR/bin/fabric-cli tokens create --location $INSTALL_DIR/id_token.json"
  fi

  echo ""
  echo "  Documentation: https://github.com/fabric-testbed/fabric_api_mcp"
  echo "============================================================"
}

# ----------------------- Main -----------------------

main() {
  detect_os
  setup_dirs

  # Always install Python venv + fabric_api_mcp (provides fabric-cli)
  setup_venv

  if $INSTALL_LOCAL; then
    # Configure fabric_rc, tokens, SSH keys (local mode only)
    setup_configure
    setup_local
  fi

  if $INSTALL_REMOTE; then
    setup_remote
  fi

  print_summary
}

main
