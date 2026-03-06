# FABRIC API MCP Server

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)
[![MCP](https://img.shields.io/badge/MCP-compatible-purple.svg)](https://modelcontextprotocol.io/)

A production-ready **[Model Context Protocol (MCP)](https://modelcontextprotocol.io/)** server that lets LLM clients (Claude Desktop, Claude Code, VS Code Copilot, ChatGPT, Chatbox, etc.) **query, provision, and manage** resources on the **[FABRIC Testbed](https://fabric-testbed.net/)** — a nation-wide programmable network research infrastructure.

### Key features

- **Two modes** — run locally (full-featured, SSH to VMs) or connect to a shared remote server
- **30+ tools** — query sites/hosts/links, build slices, modify resources, manage SSH keys, reboot nodes, and more
- **Stateless & secure** — no credentials stored; every call uses a Bearer FABRIC ID token (server mode) or local `fabric_rc` config (local mode)
- **Declarative filter DSL** — powerful filtering, sorting, and pagination on all query tools
- **Production-ready** — OpenResty reverse proxy, Prometheus metrics, Grafana dashboards, structured logging with per-request tracing
- **Resource cache** — optional background refresh for sub-second topology queries

---

## Table of contents

| Getting started | Reference | Operations |
|:---|:---|:---|
| [Quick install](#quick-install) | [Tools reference](#tools-reference) | [Deploy with Docker Compose](#deploy-with-docker-compose-server-mode) |
| [MCP client configuration](#mcp-client-configuration) | [Filter DSL & examples](#filter-dsl) | [Monitoring & Metrics](#monitoring--metrics-server-mode-only) |
| [Local mode setup](#local-mode-setup) | [Environment variables](#environment-variables) | [Adding new tools](#adding-new-tools) |
| [Remote mode setup](#remote-mode-setup) | [Architecture & repo layout](#architecture) | [Security notes](#security-notes) |
| [Local vs Remote](#local-vs-remote--which-to-use) | [Logging](#logging) / [Resource cache](#resource-cache) | |

---

## Quick install

> **Prerequisites:** Python 3.11+ and a [FABRIC account](https://portal.fabric-testbed.net/). Remote mode also requires Node.js and `jq`.

Set up FABRIC MCP with a single command:

```bash
# Local mode (full-featured: SSH to VMs, post-boot config)
curl -fsSL https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/install.sh | bash -s -- --local

# Remote mode (connects to remote MCP server via mcp-remote)
curl -fsSL https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/install.sh | bash -s -- --remote

# Both modes
curl -fsSL https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/install.sh | bash -s -- --local --remote

# Headless environment (no browser)
curl -fsSL https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/install.sh | bash -s -- --local --no-browser
```

The installer:
1. Creates `~/work/fabric-api-mcp/` with a Python venv, bin directory, and helper scripts
2. Installs `fabric_api_mcp` (which includes `fabric-cli`) into the venv
3. Runs `fabric-cli configure setup` to authenticate via CILogon and set up your FABRIC config (token, SSH keys, `fabric_rc`) in `~/work/fabric_config/`
4. Prints the configured **project ID** and MCP client config snippet

> **Project selection:** By default, your first FABRIC project is used. The installer prints the project ID at the end. To change it later:
> ```bash
> ~/work/fabric-api-mcp/venv/bin/fabric-cli configure setup --config-dir ~/work/fabric_config --projectname <name>
> # or by UUID:
> ~/work/fabric-api-mcp/venv/bin/fabric-cli configure setup --config-dir ~/work/fabric_config --projectid <uuid>
> ```

See `--help` for all options (`--config-dir`, `--venv`, `--no-browser`).

> For manual setup or more control, see [Local mode setup](#local-mode-setup) and [Remote mode setup](#remote-mode-setup) below.

---

## MCP client configuration

After installing (via the one-liner above or manually), add the FABRIC MCP server to your client. Replace `<SCRIPT>` with the path to your helper script:
- **Local mode:** `~/work/fabric-api-mcp/bin/fabric-api-local.sh` (or wherever you placed it)
- **Remote mode:** `~/work/fabric-api-mcp/bin/fabric-api.sh`

#### Claude Code CLI

```bash
claude mcp add fabric-api <SCRIPT>
```

#### Claude Desktop

Edit `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "fabric-api": {
      "command": "<SCRIPT>"
    }
  }
}
```

#### VS Code

Add to `.mcp.json` in your project root (or workspace settings):

```json
{
  "servers": {
    "fabric-api": {
      "type": "stdio",
      "command": "<SCRIPT>"
    }
  }
}
```

#### Chatbox

[Chatbox](https://chatboxai.app) (v1.14+) supports MCP servers. Go to **Settings → MCP → Add Server**, then paste this JSON:

```json
{
  "name": "fabric-api",
  "command": "<SCRIPT>",
  "args": [],
  "env": {}
}
```

Alternatively, for **remote mode** (SSE transport), use the URL-based format:

```json
{
  "name": "fabric-api",
  "url": "https://<YOUR_HOST>/mcp/sse"
}
```

---

## Tools reference

All tools accept JSON parameters and return JSON responses.

### Topology queries

| Tool | Description |
|:-----|:------------|
| `query-sites` | List sites with filters, sorting, and pagination |
| `query-hosts` | List hosts with filters, sorting, and pagination |
| `query-facility-ports` | List external facility port connections |
| `query-links` | List L2/L3 network links between sites |

### Slice lifecycle

| Tool | Description |
|:-----|:------------|
| `build-slice` | Create a slice with nodes, networks, components, switches, and facility ports |
| `query-slices` | Search/list slices or fetch a single slice by name/ID |
| `get-slivers` | List slivers (VMs, network services) within a slice |
| `modify-slice-resources` | Add or remove nodes, components, networks from an existing slice |
| `accept-modify` | Accept the last pending modification |
| `renew-slice` | Extend a slice's lease end time |
| `delete-slice` | Delete a slice by ID |
| `post-boot-config` | Configure networking inside VMs after slice reaches `StableOK` *(local mode only)* |

### Networking

| Tool | Description |
|:-----|:------------|
| `list-nodes` | List nodes in a slice with SSH commands |
| `list-networks` | List networks in a slice with subnet/gateway info |
| `list-interfaces` | List interfaces in a slice with MAC/VLAN/IP details |
| `get-network-info` | Get network details: available IPs, public IPs, gateway, subnet |
| `make-ip-publicly-routable` | Enable external access for FABNetv4Ext/FABNetv6Ext IPs |

### User & project management

| Tool | Description |
|:-----|:------------|
| `get-user-info` | Fetch user info (self or by UUID) — name, email, bastion login, roles |
| `show-my-projects` | List FABRIC projects for the current user |
| `list-project-users` | List users in a specific project |
| `get-user-keys` | Fetch a user's SSH/public keys |
| `get-bastion-username` | Get the bastion login username |

### Node operations (POA)

| Tool | Description |
|:-----|:------------|
| `add-public-key` | Add an SSH public key to a sliver |
| `remove-public-key` | Remove an SSH public key from a sliver |
| `os-reboot` | Reboot a sliver's OS |

---

## Authentication

| Mode | How it works |
|:-----|:-------------|
| **Server mode** | Every request must include `Authorization: Bearer <FABRIC_ID_TOKEN>`. The server does not store tokens. |
| **Local mode** | Credentials are read automatically from your `fabric_rc` file (`FABRIC_TOKEN_LOCATION`). No Bearer header needed. |

**Get a token:** Use `fabric-cli tokens create` (installed with this package) or download from the [FABRIC Portal → Experiments → Manage Tokens](https://portal.fabric-testbed.net/experiments#manageTokens). The token JSON contains an `id_token` field.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  MCP Client (Claude Desktop / VS Code / ChatGPT / Chatbox)     │
└──────────────────────────┬──────────────────────────────────────┘
                           │ call_tool + Bearer token (server mode)
                           │ — or stdio (local mode)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  FABRIC MCP Server (FastMCP + FastAPI)                          │
│  ├─ Tools (topology, slices, networking, user mgmt, POA)        │
│  ├─ ResourceCache (optional background refresh)                 │
│  ├─ Middleware (access log, rate limit, metrics, security)      │
│  └─ Prometheus /metrics endpoint                                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  FABRIC APIs                                                    │
│  ├─ Orchestrator (slice lifecycle, resources)                   │
│  ├─ Credential Manager (token validation)                       │
│  ├─ Core API (user info, projects, roles)                       │
│  └─ Artifact Manager (images, metadata)                         │
└─────────────────────────────────────────────────────────────────┘
```

![Architecture](./images/fabric-api.png)

- Every request carries a **x-request-id** for end-to-end tracing
- **ResourceCache** refreshes topology snapshots every 5 minutes for sub-second query responses

---

## Repo layout

```
.
├── fabric_api_mcp/              # Python package
│   ├── __main__.py              # FastMCP entrypoint
│   ├── metrics.py               # Prometheus metric definitions
│   ├── resources_cache.py       # Background topology cache
│   ├── system.md                # System prompt (served via MCP prompt)
│   ├── middleware/              # Request processing pipeline
│   │   ├── access_log.py        #   HTTP access logging
│   │   ├── metrics.py           #   Prometheus HTTP metrics
│   │   ├── rate_limit.py        #   Rate limiting
│   │   └── security_metrics.py  #   Auth failure & IP tracking
│   └── tools/                   # MCP tool implementations
│       ├── topology.py          #   Site/host/link/facility-port queries
│       └── slices/              #   Slice lifecycle, networking, POA
├── scripts/
│   ├── fabric-api-local.sh      # Local mode launcher
│   └── fabric-api.sh            # Remote mode launcher
├── nginx/
│   ├── nginx.conf               # OpenResty base config
│   └── default.conf             # Reverse proxy + Vouch auth + Lua role check
├── vouch/config                 # Vouch Proxy CILogon OIDC config
├── monitoring/
│   ├── prometheus/prometheus.yml # Scrape config
│   └── grafana/                 # Dashboards + provisioning
├── docker-compose.yml           # All 5 services
├── Dockerfile                   # MCP server image
├── pyproject.toml               # Package config (pip-installable)
├── install.sh                   # One-line installer
└── env.template                 # Template for .env
```

---

## Environment variables

Server respects these (all optional unless stated):

| Var | Default | Purpose |
|-----|---------|---------|
| `FABRIC_ORCHESTRATOR_HOST` | `orchestrator.fabric-testbed.net` | Orchestrator host |
| `FABRIC_CREDMGR_HOST` | `cm.fabric-testbed.net` | Credential manager host |
| `FABRIC_AM_HOST` | `artifacts.fabric-testbed.net` | Artifact manager host |
| `FABRIC_CORE_API_HOST` | `uis.fabric-testbed.net` | Core API host |
| `PORT` | `5000` | MCP HTTP port (internal) |
| `HOST` | `0.0.0.0` | Bind address |
| `LOG_LEVEL` | `INFO` | Python log level |
| `LOG_FORMAT` | `text` | `text` or `json` |
| `UVICORN_ACCESS_LOG` | `1` | `1/true` to emit access logs |
| `REFRESH_INTERVAL_SECONDS` | `300` | ResourceCache refresh interval |
| `CACHE_MAX_FETCH` | `5000` | Cache fetch limit per cycle |
| `MAX_FETCH_FOR_SORT` | `5000` | Max fetch when client asks to sort |
| `METRICS_ENABLED` | `1` (server) / `0` (local) | Enable Prometheus metrics + `/metrics` endpoint |
| `FABRIC_LOCAL_MODE` | `0` | `1` to enable local/stdio mode (no Bearer token required) |
| `FABRIC_MCP_TRANSPORT` | `stdio` (local) / `http` (server) | Override transport (`stdio` or `http`) |

> The `system.md` file is served to clients via an MCP prompt named **`fabric-system`**.

---

## Deploy with Docker Compose (Server Mode)

### Step 1: Clone the repository

```bash
git clone https://github.com/fabric-testbed/fabric_api_mcp.git
cd fabric-mcp
```

### Step 2: Place your TLS certificates

The NGINX reverse proxy terminates TLS and requires a certificate and private key. Update the volume paths in `docker-compose.yml` to point to your actual cert files:

```yaml
    volumes:
      - /path/to/your/fullchain.pem:/etc/ssl/public.pem
      - /path/to/your/privkey.pem:/etc/ssl/private.pem
```

Or copy/symlink them into the default location:

```bash
cp /path/to/your/fullchain.pem ssl/fullchain.pem
cp /path/to/your/privkey.pem ssl/privkey.pem
```

### Step 3: Create the `.env` file

Docker Compose reads container UIDs/GIDs from a `.env` file so that Prometheus and Grafana can write to their host bind-mount directories. Copy the template and adjust if needed:

```bash
cp env.template .env
```

The defaults match the standard container users (Prometheus = `65534`/nobody, Grafana = `472`/grafana). If your host directories are owned by a different UID/GID, update `.env` accordingly:

```bash
# Check current ownership
stat -c '%u:%g' /opt/data/production/services/api-mcp/monitoring/prometheus
stat -c '%u:%g' /opt/data/production/services/api-mcp/monitoring/grafana

# Then edit .env to match, e.g.:
# PROMETHEUS_UID=1000
# PROMETHEUS_GID=1000
```

### Step 4: Create monitoring data directories

Prometheus and Grafana persist data to host bind-mount directories. Create them and set ownership to match the UIDs in your `.env` before first start:

```bash
mkdir -p /opt/data/production/services/api-mcp/monitoring/{prometheus,grafana}
chown 65534:65534 /opt/data/production/services/api-mcp/monitoring/prometheus  # prometheus (nobody)
chown 472:472 /opt/data/production/services/api-mcp/monitoring/grafana         # grafana
```

> **Note:** The UIDs above must match `PROMETHEUS_UID`/`GRAFANA_UID` in your `.env` file.

### Step 5: Start the services

```bash
docker compose up -d
```

This starts five containers:
- **`fabric-api-mcp`** — the MCP server (port 5000, internal only)
- **`fabric-api-nginx`** — OpenResty reverse proxy (port 443, public)
- **`fabric-api-prometheus`** — Prometheus metrics collector (internal only, 30-day retention)
- **`fabric-api-grafana`** — Grafana dashboards (exposed via NGINX at `/grafana/`, protected by Vouch Proxy)
- **`fabric-api-vouch`** — Vouch Proxy for CILogon OIDC authentication (internal only)

### Step 6: Verify

```bash
# Check containers are running
docker compose ps

# Check health endpoint
curl -k https://localhost/healthz

# Check MCP server logs
docker compose logs -f mcp-server

# Check Prometheus is scraping (internal only — use docker exec)
docker compose exec prometheus wget -qO- http://localhost:9090/api/v1/targets | python3 -m json.tool
# fabric-mcp target should show state: "up"

# Check the raw metrics endpoint (internal, not exposed via NGINX)
docker compose exec mcp-server curl -s http://localhost:5000/metrics | head -20

# Access Grafana via NGINX
# Open https://<your-host>/grafana/ (login: admin/admin)
```

| Service | URL | Access |
|---------|-----|--------|
| MCP endpoint | `https://<your-host>/mcp` | Bearer token required |
| Grafana | `https://<your-host>/grafana/` | CILogon login (requires `facility-operators` or `facility-viewers` role) |
| Prometheus | Internal only (Docker network) | Via `docker compose exec prometheus ...` |

### Configuration files

The full Docker Compose and NGINX configurations are in the repository:

- **[`docker-compose.yml`](./docker-compose.yml)** — defines all 5 services (MCP server, OpenResty, Vouch Proxy, Prometheus, Grafana)
- **[`nginx/default.conf`](./nginx/default.conf)** — OpenResty reverse proxy config with Bearer token passthrough, Vouch auth for Grafana, and Lua role checking
- **[`nginx/nginx.conf`](./nginx/nginx.conf)** — base OpenResty config
- **[`vouch/config`](./vouch/config)** — Vouch Proxy CILogon OIDC settings
- **[`env.template`](./env.template)** — template for `.env` (container UIDs, CILogon credentials)

Key NGINX requirements for the MCP endpoint:
- Pass `Authorization` header: `proxy_set_header Authorization $http_authorization`
- Use HTTP/1.1: `proxy_http_version 1.1`
- Disable buffering for SSE: `proxy_buffering off`

## Adding new tools

- Add your tool function to an existing module under `fabric_api_mcp/tools/` (or create a new one) and include it in that module's `TOOLS` list.
- If you add a new module, import it in `fabric_api_mcp/tools/__init__.py` and append its `TOOLS` to `ALL_TOOLS`.
- `__main__.py` auto-registers everything in `ALL_TOOLS`, so no extra wiring is needed after export.

> The MCP server runs on port **5000** in the container (`mcp.run(transport="http", host=0.0.0.0, port=5000)`).

---

## Local mode setup

Local mode runs the MCP server on your machine using your FABRIC token file and environment — no remote server required. The server reads credentials from your `fabric_rc` file and supports all tools including `post_boot_config` (SSH into VMs).

> **Quick install:** `curl -fsSL https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/install.sh | bash -s -- --local` — automates all the steps below.

### Step 1: Create a Python virtual environment

Requires Python 3.11+ (tested with 3.13 and 3.14).

```bash
python3 -m venv ~/work/fabric-api-mcp/venv
source ~/work/fabric-api-mcp/venv/bin/activate
```

You can place the venv anywhere — just remember the path for later steps.

### Step 2: Install the package

```bash
pip install git+https://github.com/fabric-testbed/fabric_api_mcp.git
```

This installs `fabric_api_mcp` **and** `fabric-cli` (included as a dependency) into the venv.

Or clone and install in development mode:

```bash
git clone https://github.com/fabric-testbed/fabric_api_mcp.git
cd fabric-mcp
pip install -e .
```

### Step 3: Set up the FABRIC config directory

Use the **venv's** `fabric-cli` (installed as a dependency in Step 2) to set up your config. This creates the config directory, generates a token, creates bastion and sliver SSH keys, and writes `ssh_config` and `fabric_rc` files — all in one step:

```bash
~/work/fabric-api-mcp/venv/bin/fabric-cli configure setup --config-dir ~/work/fabric_config
```

This opens a browser for CILogon authentication. Once complete, it generates all required files in the config directory. Add `--no-browser` for remote/headless environments.

> **Important:** Use the venv's `fabric-cli` (`~/work/fabric-api-mcp/venv/bin/fabric-cli`), not a system-installed one, to ensure you have the correct version with the `configure` command.

> **Project selection:** By default, your first FABRIC project is used. To specify a project: `--projectid <uuid>` or `--projectname <name>`. The selected project ID is stored in `fabric_rc` as `FABRIC_PROJECT_ID`.

> **To change your project later**, re-run configure with the new project:
> ```bash
> ~/work/fabric-api-mcp/venv/bin/fabric-cli configure setup --config-dir ~/work/fabric_config --projectname <name>
> ```

**Alternatively**, set up manually. The config directory should contain:
- **`fabric_rc`** — environment file that exports FABRIC variables (token location, SSH key paths, etc.)
- **`tokens.json`** — your FABRIC token file (downloaded from the [FABRIC Portal → Experiments → Manage Tokens](https://portal.fabric-testbed.net/experiments#manageTokens))
- **SSH keys** — bastion key, slice key, and slice key `.pub` (see [Portal → Experiments → SSH Keys](https://portal.fabric-testbed.net/experiments#sshKeys))

A minimal `fabric_rc` looks like:

```bash
export FABRIC_CREDMGR_HOST=cm.fabric-testbed.net
export FABRIC_ORCHESTRATOR_HOST=orchestrator.fabric-testbed.net
export FABRIC_CORE_API_HOST=uis.fabric-testbed.net

export FABRIC_PROJECT_ID=<your-project-uuid>
export FABRIC_TOKEN_LOCATION=~/work/fabric_config/tokens.json

export FABRIC_BASTION_HOST=bastion.fabric-testbed.net
export FABRIC_BASTION_USERNAME=<your_bastion_username>

export FABRIC_BASTION_KEY_LOCATION=~/work/fabric_config/fabric_bastion_key
export FABRIC_SLICE_PRIVATE_KEY_FILE=~/work/fabric_config/slice_key
export FABRIC_SLICE_PUBLIC_KEY_FILE=~/work/fabric_config/slice_key.pub

export FABRIC_LOG_FILE=~/fablib.log
export FABRIC_LOG_LEVEL=INFO

export FABRIC_SSH_COMMAND_LINE="ssh -i {{ _self_.private_ssh_key_file }} -F ~/work/fabric_config/ssh_config {{ _self_.username }}@{{ _self_.management_ip }}"
```

Replace `<your-project-uuid>` and `<your_bastion_username>` with your actual values from the FABRIC portal.

### Step 4: Get the helper script

If you cloned the repo, the script is already at `scripts/fabric-api-local.sh`.

Otherwise, download it:

```bash
curl -o ~/fabric-api-local.sh \
  https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/scripts/fabric-api-local.sh
chmod +x ~/fabric-api-local.sh
```

### Step 5: Configure the script for your environment

The script defaults are shown below. Update if your paths differ — either edit the script directly or override at runtime via env vars:

| Var | Default | Purpose |
|-----|---------|---------|
| `FABRIC_VENV` | `~/work/fabric-api-mcp/venv` | Path to your Python venv |
| `FABRIC_RC` | `~/work/fabric_config/fabric_rc` | Path to your `fabric_rc` file |

If you used a different venv path in Step 1, update accordingly:

```bash
# Override at runtime:
FABRIC_VENV=~/my-other-venv ./scripts/fabric-api-local.sh

# Or edit the script default directly
```

### Step 6: Test

```bash
~/fabric-api-local.sh
# or if using cloned repo:
./scripts/fabric-api-local.sh
```

You should see the MCP server start in stdio mode. Press `Ctrl+C` to stop.

### Step 7: Configure your MCP client

See [MCP client configuration](#mcp-client-configuration) — use the path to your `fabric-api-local.sh` script as `<SCRIPT>`.

---

## Remote mode setup

Remote mode connects to a Docker Compose-deployed MCP server over HTTPS. It uses `mcp-remote` to bridge stdio to the remote endpoint and sends a Bearer token with each request.

> **Quick install:** `curl -fsSL https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/install.sh | bash -s -- --remote` — automates all the steps below. The installer sets up a Python venv with `fabric_api_mcp` + `fabric-cli` (for token management), then installs `jq` and Node.js.

### Step 1: Install prerequisites

Remote mode requires Python 3.11+ (for the venv with `fabric-cli`), plus `jq` and `npx` (`mcp-remote`):

```bash
# macOS
brew install jq node

# Linux
sudo apt install jq nodejs npm
```

### Step 2: Set up the venv

Create a Python venv and install `fabric_api_mcp` (which includes `fabric-cli`):

```bash
python3 -m venv ~/work/fabric-api-mcp/venv
~/work/fabric-api-mcp/venv/bin/pip install git+https://github.com/fabric-testbed/fabric_api_mcp.git
```

### Step 3: Create your token

Use the venv's `fabric-cli` to create a token:

```bash
~/work/fabric-api-mcp/venv/bin/fabric-cli tokens create --tokenlocation ~/work/fabric-api-mcp/id_token.json
```

This opens a browser for CILogon authentication, then saves the token automatically.

> If running on a remote/headless VM, add `--no-browser` and follow the printed URL manually. Press `Ctrl+C` after login and paste the authorization code.

Alternatively, download your token from the [FABRIC Portal → Experiments → Manage Tokens](https://portal.fabric-testbed.net/experiments#manageTokens):

```bash
cp /path/to/downloaded/token.json ~/work/fabric-api-mcp/id_token.json
```

### Step 4: Get the helper script

If you cloned the repo, the script is already at `scripts/fabric-api.sh`.

Otherwise, download it:

```bash
curl -o ~/fabric-api.sh \
  https://raw.githubusercontent.com/fabric-testbed/fabric_api_mcp/main/scripts/fabric-api.sh
chmod +x ~/fabric-api.sh
```

### Step 5: Configure the script

Update these if your paths or server URL differ from the defaults:

| Var | Default | Purpose |
|-----|---------|---------|
| `FABRIC_TOKEN_JSON` | `~/work/fabric-api-mcp/id_token.json` | Path to JSON file containing `{"id_token": "..."}` |
| `FABRIC_MCP_URL` | `https://api-mcp.fabric-testbed.net/mcp` | URL of the remote MCP server |

### Step 6: Test

```bash
~/fabric-api.sh
# or if using cloned repo:
./scripts/fabric-api.sh
```

The script reads your token and connects to the remote MCP server via `mcp-remote`.

### Step 7: Configure your MCP client

See [MCP client configuration](#mcp-client-configuration) — use the path to your `fabric-api.sh` script as `<SCRIPT>`.

---

## Local vs Remote — which to use?

| | Local mode | Remote mode |
|:---|:-----------|:-------------|
| **Script** | `fabric-api-local.sh` | `fabric-api.sh` |
| **Auth** | Automatic from `fabric_rc` | Bearer token via `id_token.json` |
| **Transport** | stdio (direct) | stdio → `mcp-remote` → HTTPS |
| **Server** | Runs on your machine | Shared Docker Compose deployment |
| **Post-boot config** | Yes (SSH access to VMs) | No (no SSH access) |
| **All tools available** | Yes (30+ tools) | All except `post-boot-config` |
| **Dependencies** | Python 3.11+ | Python 3.11+ / Node.js / `jq` |
| **Best for** | Full-featured development & experimentation | Quick queries, shared team server |

> **Recommendation:** Use **local mode** for the best experience — it supports all tools including SSH-based post-boot configuration of VMs.

---

## Filter DSL

All `query-*` tools support a declarative JSON filter DSL with sorting and pagination.

### Operators

| Operator | Description | Example |
|:---------|:------------|:--------|
| `eq` | Equals | `{"name": {"eq": "UCSD"}}` |
| `ne` | Not equals | `{"state": {"ne": "Dead"}}` |
| `lt`, `lte`, `gt`, `gte` | Numeric comparisons | `{"cores_available": {"gte": 32}}` |
| `in` | Value in list | `{"name": {"in": ["RENC", "UCSD", "STAR"]}}` |
| `contains` | Substring, key, or element match | `{"components": {"contains": "GPU"}}` |
| `icontains` | Case-insensitive contains | `{"name": {"icontains": "utah"}}` |
| `regex` | Regex match | `{"name": {"regex": "(?i)^u.*"}}` |
| `any`, `all` | List quantifiers | `{"hosts": {"any": {"icontains": "gpu"}}}` |

Logical OR: `{"or": [{"name": {"eq": "UCSD"}}, {"name": {"eq": "STAR"}}]}`

### Sorting & pagination

```json
{"sort": {"field": "cores_available", "direction": "desc"}, "limit": 50, "offset": 0}
```

Response format: `{"items": [...], "total": 150, "count": 50, "offset": 0, "has_more": true}`

---

## Quick tool examples

**Query hosts at UCSD with GPUs, sorted by free cores**

```jsonc
{
  "tool": "query-hosts",
  "params": {
    "filters": {"site": {"eq": "UCSD"}, "components": {"contains": "GPU"}},
    "sort": { "field": "cores_available", "direction": "desc" },
    "limit": 50
  }
}
```

**POA: reboot a node’s sliver**

```jsonc
{
  "tool": "os-reboot",
  "params": {
    "sliver_id": "<SLIVER-UUID>"
  }
}
```

**Build and submit a slice**

```jsonc
{
  "tool": "build-slice",
  "params": {
    "name": "demo-slice",
    "ssh_keys": ["ssh-ed25519 AAAA... user@example"],
    "nodes": [
      {
        "name": "node1",
        "site": "UCSD",
        "cores": 4,
        "ram": 16,
        "disk": 50,
        "image": "default_rocky_8",
        "components": [
          { "model": "GPU_TeslaT4", "name": "gpu0" }
        ]
      },
      {
        "name": "node2",
        "site": "RENC",
        "cores": 8,
        "ram": 32,
        "disk": 100
      }
    ],
    "networks": [
      {
        "name": "net1",
        "type": "L2PTP",
        "nodes": ["node1", "node2"],
        "bandwidth": 10
      }
    ],
    "lifetime": 60
  }
}
```

**Valid component models**

| Category | Models |
|:---------|:-------|
| GPUs | `GPU_TeslaT4`, `GPU_RTX6000`, `GPU_A40`, `GPU_A30` |
| NICs | `NIC_Basic`, `NIC_ConnectX_5`, `NIC_ConnectX_6`, `NIC_ConnectX_7_100` (100G), `NIC_ConnectX_7_400` (400G) |
| Storage | `NVME_P4510` |
| FPGAs | `FPGA_Xilinx_U280`, `FPGA_Xilinx_SN1022` |

**Network types**

| Type | Scope | Description |
|:-----|:------|:------------|
| `L2Bridge` | Single-site | Local bridge |
| `L2STS` | Cross-site | Site-to-site L2 (default for multi-site) |
| `L2PTP` | Cross-site | Point-to-point with ERO for dedicated QoS |
| `L2` | Auto | Shorthand — auto-selects `L2Bridge` or `L2STS` |
| `FABNetv4` / `FABNetv6` | Per-site | Orchestrator-assigned L3 subnet |
| `FABNetv4Ext` / `FABNetv6Ext` | Per-site | Externally routable L3 (use `make-ip-publicly-routable`) |
| `IPv4` / `IPv6` / `IPv4Ext` / `IPv6Ext` | — | Aliases for the FABNet types above |

**Auto-selection behavior:**
- **NIC**: auto-selected based on network type and bandwidth (100 Gbps → `NIC_ConnectX_6`, 25 Gbps → `NIC_ConnectX_5`, default → `NIC_Basic`). Override with `nic` in network spec.
- **Site**: if omitted from a node, a random site with sufficient resources is chosen. Nodes are spread across different sites when possible.
- **Multi-site FABNet***: creates per-site networks automatically (e.g., `mynet-UTAH`, `mynet-STAR`)

**IP Assignment by Network Type**

| Network Type | Subnet | IP Assignment |
|--------------|--------|---------------|
| L2 (L2PTP, L2STS, L2Bridge) | User chooses any subnet | Manual assignment inside VMs |
| L3 (FABNetv4, FABNetv6) | Orchestrator assigns | Assign from orchestrator's subnet |
| L3 Ext (FABNetv4Ext, FABNetv6Ext) | Orchestrator assigns | Use `make-ip-publicly-routable`, configure **returned** IP |

- **FABNetv4Ext**: IPv4 subnet is **shared** across all slices at the site. Requested IP may be in use; orchestrator returns actual available IP. After calling `make-ip-publicly-routable`, always re-fetch with `get-network-info` and use the **returned** `public_ips` value.
- **FABNetv6Ext**: Entire IPv6 subnet is **dedicated** to your slice. Any IP from the subnet can be requested.
- **After modify**: When adding FABNetv4Ext/FABNetv6Ext via `modify-slice-resources`, wait for `ModifyOK` state before fetching network info and enabling public routing.

**SSH Access to VMs**

To access FABRIC VMs, you need:
1. **Bastion keys** — Create at https://portal.fabric-testbed.net/experiments#sshKeys
2. **Slice SSH keys** — The keys specified when creating the slice
3. **SSH config** — Configure your `~/.ssh/config`:

```
UserKnownHostsFile /dev/null
StrictHostKeyChecking no
ServerAliveInterval 120

Host bastion.fabric-testbed.net
    User <bastion_login>
    ForwardAgent yes
    Hostname %h
    IdentityFile ~/.ssh/bastion_key
    IdentitiesOnly yes

Host * !bastion.fabric-testbed.net
    ProxyJump <bastion_login>@bastion.fabric-testbed.net:22
```

Replace `<bastion_login>` with your bastion username (from `get-user-info` tool, e.g., `kthare10_0011904101`).

**Example SSH command:**
```bash
ssh -i /path/to/slice_key -F /path/to/ssh_config ubuntu@<vm_ipv6_address>
```

The VM's management IP (IPv6) is available from `get-slivers` output.

---

## System prompt

Your `fabric_api_mcp/system.md` is exposed to clients via:

```python
@mcp.prompt(name="fabric-system")
def fabric_system_prompt():
    return Path("system.md").read_text().strip()
```

Put guardrails here (token validation reminders, exclusions, etc.).

---

## Logging

* Structured per-request access logs (opt-in via `UVICORN_ACCESS_LOG=1`)
* App logs support `text` or `json` format via `LOG_FORMAT`
* Each HTTP request and tool call carries a **request_id** (also returned as `x-request-id`)

Example JSON log:

```json
{"ts":"2025-11-06T18:22:10+0000","level":"INFO","logger":"fabric.mcp",
 "msg":"Tool done in 85.31ms (size=42)","tool":"query-hosts","request_id":"9a7c3e1b12ac"}
```

---

## Resource cache

The server wires a `ResourceCache` (if present) to periodically refresh public topology/resource snapshots:

* Interval: `REFRESH_INTERVAL_SECONDS` (default 300s)
* Fetch limit: `CACHE_MAX_FETCH` (default 5000)
* Sorting big lists: `MAX_FETCH_FOR_SORT` (default 5000)

This accelerates `query-sites`, `query-hosts`, `query-facility-ports`, `query-links`.

---

## Monitoring & Metrics (Server Mode Only)

The MCP server includes built-in Prometheus metrics and a pre-configured Grafana dashboard. Metrics are **enabled by default in server mode** and **disabled in local mode**. Override with `METRICS_ENABLED=0` or `METRICS_ENABLED=1`.

### Architecture

```
Client → NGINX (:443) → MCP Server (:5000)
                  ↓
           /grafana/ → Grafana (:3000) → Prometheus (:9090) → MCP Server (:5000/metrics)
```

- All services are on the internal `frontend` Docker network
- `/metrics` endpoint is internal only — **not** exposed through NGINX
- Prometheus and Grafana have **no ports exposed** to the host — Grafana is accessed via NGINX at `/grafana/`
- Prometheus data is retained for **30 days** (~100-500 MB depending on cardinality)
- Data is persisted to NFS at `/opt/data/production/services/api-mcp/monitoring/`

### Accessing the dashboard

After `docker compose up -d`:

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | `https://<your-host>/grafana/` | CILogon login (requires `facility-operators` or `facility-viewers` role) |
| Prometheus | Internal only | `docker compose exec prometheus ...` |

In Grafana, the **FABRIC MCP** dashboard is auto-provisioned and available immediately.

### Available metrics

#### HTTP metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `mcp_http_requests_total` | Counter | `method`, `path`, `status` | Total HTTP requests |
| `mcp_http_request_duration_seconds` | Histogram | `method`, `path` | Request latency |
| `mcp_http_requests_in_progress` | Gauge | `method` | Currently active requests |

#### Tool metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `mcp_tool_calls_total` | Counter | `tool`, `user_uuid`, `user_email`, `project_name`, `status` | Tool calls (who called what, from which project) |
| `mcp_tool_call_duration_seconds` | Histogram | `tool` | Tool execution latency |

User identity uses the **FABRIC user UUID** (a GUID from the JWT `uuid` claim) and **email** (`email` claim), not the CILogon `sub` URI. Project name is extracted from the first project in the JWT `projects` claim.

#### Per-user / access log metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `mcp_requests_by_user_total` | Counter | `user_uuid`, `user_email` | Total requests per user |
| `mcp_requests_by_user_path_total` | Counter | `user_uuid`, `user_email`, `method`, `path` | Per-user per-endpoint breakdown |
| `mcp_rate_limit_hits_total` | Counter | `key_type` | Rate limit 429 responses |

#### Security metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `mcp_auth_failures_total` | Counter | `reason`, `client_ip` | Auth failures by reason and source IP |
| `mcp_auth_success_total` | Counter | `user_uuid`, `user_email`, `client_ip` | Successful auth by user + IP |
| `mcp_requests_by_ip_total` | Counter | `client_ip` | All requests by source IP |

Auth failure reasons: `missing_token`, `malformed_header`, `invalid_jwt`, `expired_token`.

### Grafana dashboard panels

The pre-built **FABRIC MCP** dashboard is organized into 4 sections with 19 panels:

**Overview:**
- Request rate (total / 5xx / 429)
- Request latency percentiles (p50, p95, p99)
- Active requests gauge
- Error rate percentage
- Rate limit hits over time

**Tool Calls:**
- Tool call rate by tool name
- Tool latency by tool (p95)
- Tool errors by tool
- Tool calls by user (email + UUID → tool, with call count)
- Tool calls total by tool (pie chart — tool usage distribution)
- Tool calls by project (project + email → tool breakdown)

**Users & Access:**
- Top users by total request count (email + UUID)
- Requests by user + endpoint (email + method + path)

**Security:**
- Auth failures by reason (stacked time series)
- Auth failures by IP (table — spot brute-force or overseas probing)
- Top client IPs by request volume
- User-to-IP mapping (table — spot token reuse from unexpected locations)

### Example Prometheus queries

```promql
# Request rate over last 5 minutes
sum(rate(mcp_http_requests_total[5m]))

# p95 latency for all tool calls
histogram_quantile(0.95, sum(rate(mcp_tool_call_duration_seconds_bucket[5m])) by (le, tool))

# Which tools did a specific user call?
sum(mcp_tool_calls_total{user_email="user@example.edu"}) by (tool)

# Tool calls by project
sum(mcp_tool_calls_total) by (project_name, tool)

# Auth failures from a specific IP in the last hour
sum(increase(mcp_auth_failures_total{client_ip="203.0.113.42"}[1h]))

# Users authenticating from multiple IPs (possible token sharing)
count(mcp_auth_success_total) by (user_email) > 3

# Top 10 users by request count in the last 24h
topk(10, sum(increase(mcp_requests_by_user_total[24h])) by (user_email, user_uuid))
```

### Disabling metrics

Set `METRICS_ENABLED=0` in the MCP server environment. This disables:
- The `/metrics` endpoint
- All Prometheus metric collection (HTTP, tool, security)
- The `prometheus-client` library is never imported (zero overhead)

Prometheus and Grafana containers can still run but will have no data to scrape.

### Grafana authentication (Vouch Proxy + CILogon)

Grafana is protected by [Vouch Proxy](https://github.com/vouch/vouch-proxy) using CILogon OIDC. Only users with `facility-operators` or `facility-viewers` roles can access dashboards. NGINX (OpenResty) forwards the vouch session cookie to the FABRIC Core API to check user roles via Lua.

**Setup:**

1. **Register a CILogon OIDC client** at https://cilogon.org/oauth2/register
   - Set the callback URL to `https://<your-host>/auth`
   - Note the `client_id` and `client_secret`

2. **Configure environment variables** in your `.env` file (see `env.template`):
   ```
   VOUCH_HOSTNAME=your-mcp-host.fabric-testbed.net
   CILOGON_CLIENT_ID=your-cilogon-client-id
   CILOGON_CLIENT_SECRET=your-cilogon-client-secret
   ```

3. **Update the Vouch config** — replace placeholders in `vouch/config`:
   - `VOUCH_HOSTNAME` → your server hostname
   - `CILOGON_CLIENT_ID` / `CILOGON_CLIENT_SECRET` → from step 1
   - Ensure `publicAccess: false` (required — if `true`, vouch passes unauthenticated requests)

4. **Start services** — `docker compose up -d` now starts 5 containers (adds `vouch-proxy`)

**How it works:**
- Unauthenticated requests to `/grafana/` are redirected to CILogon login via Vouch Proxy
- After login, Vouch Proxy sets a session cookie (`fabric-service` on the `fabric-testbed.net` domain)
- On each request, NGINX's `auth_request` calls Vouch to validate the session
- A Lua `access_by_lua_block` then forwards the vouch cookie to the FABRIC Core API:
  1. `GET /whoami` → retrieves the user's UUID
  2. `GET /people/{uuid}?as_self=true` → retrieves the user's roles
  3. Checks for `facility-operators` or `facility-viewers` in the roles list
- Role check results are cached for 5 minutes (`lua_shared_dict role_cache`) to avoid repeated API calls
- Users without the required roles get a 403 Forbidden response
- Grafana is configured for anonymous viewer access (auth is enforced at the NGINX layer)
- The `/mcp` endpoint is **not affected** — it continues using Bearer token auth

### Production considerations

- **Grafana access control**: Grafana is protected by Vouch Proxy + CILogon at the NGINX layer. Only users with `facility-operators` or `facility-viewers` roles can access it. Grafana itself uses anonymous viewer access (the admin password is only needed for dashboard editing via CLI).
- **No exposed ports**: Prometheus and Grafana have no ports exposed to the host. Grafana is served through NGINX at `/grafana/`. Prometheus is accessible only from within the Docker network.
- **Data retention**: Prometheus is configured with 30-day retention (`--storage.tsdb.retention.time=30d`). Estimated disk usage is ~100-500 MB for 30 days depending on user/tool cardinality.
- **NFS persistence**: Prometheus and Grafana data directories are bind-mounted to `/opt/data/production/services/api-mcp/monitoring/`. Container UIDs are configured via `.env` (copy from `env.template`). Ensure host directory ownership matches the UIDs in your `.env` file.
- **Client IP forwarding**: NGINX forwards the real client IP via `X-Real-IP` and `X-Forwarded-For` headers. These must be set inside each `location` block (NGINX does not inherit `proxy_set_header` from the server block when a location defines its own).
- **Alerting**: Add Prometheus alerting rules (e.g., alert on auth failure spikes, error rate > 5%) and configure Grafana notification channels (email, Slack, PagerDuty).

---

## Security notes

* Tokens are accepted only via **Authorization header**; they are **not stored**.
* Do not print tokens in logs. (Server code avoids this.)
* Terminate TLS at NGINX; keep the MCP service on an internal network.
* Rotate TLS certs and restrict `client_max_body_size` if desired.
* **Auth monitoring**: Prometheus tracks auth failures (missing/malformed/invalid/expired tokens) by client IP, and successful auth by user (UUID + email) + IP pair. Tool calls are tracked per user and FABRIC project. Use the Grafana security panels or Prometheus queries to detect brute-force attempts, overseas probing, and token reuse from unexpected locations.

---

## License

[MIT](./LICENSE).
