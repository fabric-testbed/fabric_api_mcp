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

INSTALL_DIR="$HOME/.fabric-api-mcp"
BIN_DIR="$INSTALL_DIR/bin"
VENV_DIR=""
CONFIG_DIR=""
INSTALL_LOCAL=false
INSTALL_REMOTE=false
NO_BROWSER=false

GITHUB_RAW="https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main"

# ----------------------- Helpers -----------------------

info()  { printf '\033[1;34m[info]\033[0m  %s\n' "$*"; }
ok()    { printf '\033[1;32m[ok]\033[0m    %s\n' "$*"; }
warn()  { printf '\033[1;33m[warn]\033[0m  %s\n' "$*"; }
err()   { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }
die()   { err "$@"; exit 1; }

usage() {
  cat <<'EOF'
Usage: install.sh [OPTIONS]

Options:
  --local              Set up local mode (Python venv, fabric-cli, full features)
  --remote             Set up remote mode (jq + Node.js, lightweight)
  --config-dir <path>  Override FABRIC config directory (default: ~/.fabric-api-mcp/fabric_config)
  --venv <path>        Override Python venv path (default: ~/.fabric-api-mcp/venv)
  --no-browser         Pass --no-browser to fabric-cli (for headless environments)
  --help               Show this help message

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
CONFIG_DIR="${CONFIG_DIR:-$INSTALL_DIR/fabric_config}"

# ----------------------- OS detection -----------------------

detect_os() {
  case "$(uname -s)" in
    Darwin*) OS="macos" ;;
    Linux*)  OS="linux" ;;
    *)       die "Unsupported OS: $(uname -s)" ;;
  esac

  if [[ "$OS" == "linux" ]]; then
    if command -v apt-get >/dev/null 2>&1; then
      PKG_MGR="apt"
    elif command -v yum >/dev/null 2>&1; then
      PKG_MGR="yum"
    elif command -v dnf >/dev/null 2>&1; then
      PKG_MGR="dnf"
    else
      PKG_MGR="unknown"
    fi
  else
    if command -v brew >/dev/null 2>&1; then
      PKG_MGR="brew"
    else
      PKG_MGR="unknown"
    fi
  fi

  info "Detected OS: $OS, package manager: $PKG_MGR"
}

# ----------------------- Package install helpers -----------------------

pkg_install() {
  local pkg="$1"
  case "$PKG_MGR" in
    brew) brew install "$pkg" ;;
    apt)  sudo apt-get update -qq && sudo apt-get install -y -qq "$pkg" ;;
    yum)  sudo yum install -y "$pkg" ;;
    dnf)  sudo dnf install -y "$pkg" ;;
    *)    die "Cannot install $pkg: no supported package manager found. Install it manually." ;;
  esac
}

ensure_command() {
  local cmd="$1"
  local pkg="${2:-$1}"
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd is already installed"
  else
    info "Installing $pkg..."
    pkg_install "$pkg"
    if ! command -v "$cmd" >/dev/null 2>&1; then
      die "Failed to install $cmd. Please install it manually and re-run."
    fi
    ok "$cmd installed"
  fi
}

# ----------------------- Python helpers -----------------------

ensure_python() {
  # Check for python3.11+
  local py=""
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      local ver
      ver="$("$candidate" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)"
      if [[ "$ver" -ge 11 ]]; then
        py="$candidate"
        break
      fi
    fi
  done

  if [[ -n "$py" ]]; then
    ok "Python 3.11+ found: $py ($($py --version))"
    PYTHON="$py"
    return
  fi

  info "Python 3.11+ not found, installing..."
  case "$PKG_MGR" in
    brew) brew install python@3.13 ;;
    apt)  sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-venv python3-pip ;;
    yum)  sudo yum install -y python3 python3-pip ;;
    dnf)  sudo dnf install -y python3 python3-pip ;;
    *)    die "Cannot install Python. Install Python 3.11+ manually and re-run." ;;
  esac

  # Re-detect
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      local ver
      ver="$("$candidate" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)"
      if [[ "$ver" -ge 11 ]]; then
        PYTHON="$candidate"
        ok "Python installed: $PYTHON ($($PYTHON --version))"
        return
      fi
    fi
  done

  die "Could not find Python 3.11+ after installation. Install it manually and re-run."
}

# ----------------------- Common setup -----------------------

setup_dirs() {
  info "Creating install directory: $INSTALL_DIR"
  mkdir -p "$BIN_DIR"
  ok "Directories created"
}

# ----------------------- Local mode setup -----------------------

setup_local() {
  info "=== Setting up LOCAL mode ==="

  # 1. Ensure Python 3.11+
  ensure_python

  # 2. Install fabric-cli (for token creation + config setup)
  if command -v fabric-cli >/dev/null 2>&1; then
    ok "fabric-cli is already installed"
  else
    info "Installing fabric-cli..."
    "$PYTHON" -m pip install --quiet --user fabric-cli
    if command -v fabric-cli >/dev/null 2>&1; then
      ok "fabric-cli installed"
    else
      warn "fabric-cli installed but not on PATH. It may be in ~/.local/bin/"
      export PATH="$HOME/.local/bin:$PATH"
    fi
  fi

  # 3. Create Python venv
  if [[ -d "$VENV_DIR" ]]; then
    ok "Python venv already exists: $VENV_DIR"
  else
    info "Creating Python venv at $VENV_DIR..."
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Venv created"
  fi

  # 4. Install fabric_api_mcp into venv
  info "Installing fabric_api_mcp into venv..."
  "$VENV_DIR/bin/pip" install --quiet --upgrade pip
  "$VENV_DIR/bin/pip" install --quiet "git+https://github.com/fabric-testbed/fabric_api_mcp.git"
  ok "fabric_api_mcp installed"

  # 5. Create config dir
  mkdir -p "$CONFIG_DIR"
  ok "Config directory: $CONFIG_DIR"

  # 6. Run fabric-cli configure setup (interactive)
  if [[ -f "$CONFIG_DIR/fabric_rc" ]]; then
    ok "fabric_rc already exists at $CONFIG_DIR/fabric_rc — skipping configure"
  else
    info "Running fabric-cli configure setup..."
    info "This will open a browser for CILogon authentication."
    local cli_args=(configure setup --config-dir "$CONFIG_DIR")
    if $NO_BROWSER; then
      cli_args+=(--no-browser)
    fi
    if command -v fabric-cli >/dev/null 2>&1; then
      fabric-cli "${cli_args[@]}" || {
        warn "fabric-cli configure setup failed or was cancelled."
        warn "You can run it later: fabric-cli configure setup --config-dir $CONFIG_DIR"
      }
    else
      warn "fabric-cli not found on PATH. Run manually after install:"
      warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
      warn "  fabric-cli configure setup --config-dir $CONFIG_DIR"
    fi
  fi

  # 7. Download fabric-api-local.sh
  info "Downloading fabric-api-local.sh..."
  curl -fsSL "$GITHUB_RAW/scripts/fabric-api-local.sh" -o "$BIN_DIR/fabric-api-local.sh"
  chmod +x "$BIN_DIR/fabric-api-local.sh"

  # Patch defaults to point to installed paths
  sed -i.bak "s|FABRIC_VENV:-\$HOME/fabric-mcp-venv|FABRIC_VENV:-$VENV_DIR|" "$BIN_DIR/fabric-api-local.sh"
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

  # 3. Create token (if fabric-cli is available)
  local token_dir="$INSTALL_DIR"
  local token_file="$token_dir/id_token.json"
  if [[ -f "$token_file" ]]; then
    ok "Token file already exists: $token_file"
  else
    if command -v fabric-cli >/dev/null 2>&1; then
      info "Creating FABRIC token via fabric-cli..."
      local cli_args=(tokens create --tokenlocation "$token_file")
      if $NO_BROWSER; then
        cli_args+=(--no-browser)
      fi
      fabric-cli "${cli_args[@]}" || {
        warn "Token creation failed or was cancelled."
        warn "You can create a token later:"
        warn "  fabric-cli tokens create --tokenlocation $token_file"
        warn "Or download from: https://portal.fabric-testbed.net/experiments#manageTokens"
      }
    else
      warn "fabric-cli not available. Download your token manually:"
      warn "  1. Go to https://portal.fabric-testbed.net/experiments#manageTokens"
      warn "  2. Save the token JSON to: $token_file"
    fi
  fi

  # 4. Download fabric-api.sh
  info "Downloading fabric-api.sh..."
  curl -fsSL "$GITHUB_RAW/scripts/fabric-api.sh" -o "$BIN_DIR/fabric-api.sh"
  chmod +x "$BIN_DIR/fabric-api.sh"

  # Patch default token path to installed location
  sed -i.bak "s|FABRIC_TOKEN_JSON:-\$HOME/work/claude/id_token.json|FABRIC_TOKEN_JSON:-$token_file|" "$BIN_DIR/fabric-api.sh"
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

  if $INSTALL_LOCAL; then
    echo ""
    echo "  --- Local mode ---"
    echo "  Script:   $BIN_DIR/fabric-api-local.sh"
    echo "  Venv:     $VENV_DIR"
    echo "  Config:   $CONFIG_DIR"
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
  if $INSTALL_LOCAL && [[ ! -f "$CONFIG_DIR/fabric_rc" ]]; then
    echo "    1. Run: fabric-cli configure setup --config-dir $CONFIG_DIR"
    echo "    2. Add the MCP server to your client (see config above)"
  else
    echo "    1. Add the MCP server to your client (see config above)"
  fi
  echo ""
  echo "  Documentation: https://github.com/fabric-testbed/fabric_api_mcp"
  echo "============================================================"
}

# ----------------------- Main -----------------------

main() {
  detect_os
  setup_dirs

  if $INSTALL_LOCAL; then
    setup_local
  fi

  if $INSTALL_REMOTE; then
    setup_remote
  fi

  print_summary
}

main
