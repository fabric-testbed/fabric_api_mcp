# FABRIC API MCP Server

A production-ready **Model Context Protocol (MCP)** server that exposes **FABRIC Testbed API** and inventory queries through `fabric_manager_v2`, designed for secure, token-based use by LLM clients (ChatGPT MCP, VS Code, Claude Desktop, etc.).

- **Stateless**: no user credentials stored; every call uses a **Bearer FABRIC ID token**
- **Deterministic tools** with strong logging, request IDs, and JSON/text log formats
- **Reverse-proxy friendly**: ships with NGINX front end
- **Resource cache** (optional) for fast site/host/link queries

---

## What this server provides

### Exposed MCP tools (from this codebase)
- `query-sites` — list sites (filters, sort, pagination)
- `query-hosts` — list hosts (filters, sort, pagination)
- `query-facility-ports` — list facility ports
- `query-links` — list L2/L3 links
- `query-slices` — search/list slices or fetch a single slice
- `get-slivers` — list slivers for a slice
- `renew-slice` — renew slice by `lease_end_time`
- `delete-slice` — delete a slice (by ID)
- `modify-slice` — modify an existing slice
- `accept-modify` — accept the last modify
- `build-slice` — build and submit a slice with nodes, components, and networks
- `show-my-projects` — list projects for the current user (or specified UUID)
- `list-project-users` — list users in a project
- `get-user-keys` — fetch a user's SSH/public keys
- `add-public-key` — add a public key to a sliver (POA addkey)
- `remove-public-key` — remove a public key from a sliver (POA removekey)
- `os-reboot` — reboot a sliver (POA)

> All tools expect JSON params and return JSON.

---

## Authentication

Every MCP call **must include** a FABRIC ID token:

```

Authorization: Bearer <FABRIC_ID_TOKEN>

```

Obtain tokens via the FABRIC Portal → **Experiments → Manage Tokens** (the token JSON contains `id_token`).

This server **does not** read any local token/config files and **does not persist** tokens.

---

## Architecture

```

MCP Client (ChatGPT / VSCode / Claude)
└─(call_tool + Authorization: Bearer <token>)
FABRIC Provisioning MCP Server (FastMCP + FastAPI)
└─ FabricManagerV2 (token-based calls)
└─ FABRIC Orchestrator / APIs

```
![Architecture](./images/fabric-api.png)

- Access logs include a per-request **x-request-id** for tracing
- Optional **ResourceCache**: background refresher for fast `query-*` responses

---

## Repo layout 

```

.
├─ server/
│  ├─ __main__.py            # FastMCP entrypoint (`python -m server`)
│  ├─ resources_cache.py     # background cache
│  ├─ system.md              # system prompt served via @mcp.prompt("fabric-system")
│  ├─ tools/
│  │  ├─ topology.py         # topology query tools
│  │  └─ slices/             # slice tools split by concern
│  ├─ requirements.txt
│  └─ Dockerfile
├─ nginx/
│  ├─ nginx.conf
│  └─ default.conf           # reverse proxy to mcp-server
├─ ssl/
│  ├─ fullchain.pem
│  └─ privkey.pem
├─ docker-compose.yml
└─ README.md                 # <— this file

````

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

> The `system.md` file is served to clients via an MCP prompt named **`fabric-system`**.

---

## Deploy with Docker Compose

Your provided `docker-compose.yml` (works as-is):

```yaml
services:
  mcp-server:
    build:
      context: server/
      dockerfile: Dockerfile
    container_name: fabric-prov-mcp
    image: fabric-prov-mcp:latest
    restart: always
    networks:
      - frontend
    environment:
      FABRIC_ORCHESTRATOR_HOST: orchestrator.fabric-testbed.net
      FABRIC_AM_HOST: artifacts.fabric-testbed.net
      FABRIC_CORE_API_HOST: uis.fabric-testbed.net
      FABRIC_CREDMGR_HOST: cm.fabric-testbed.net
    volumes:
      - ./mcp-logs:/var/log/mcp

  nginx:
    image: library/nginx:1
    container_name: fabric-prov-nginx
    networks:
      - frontend
      - backend
    ports:
      - 443:443
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./ssl/fullchain.pem:/etc/ssl/public.pem
      - ./ssl/privkey.pem:/etc/ssl/private.pem
      - ./nginx-logs:/var/log/nginx
    restart: always

networks:
  frontend:
  backend:
    internal: true
````

### Minimal NGINX `default.conf`

Make sure Authorization headers pass through and HTTP/1.1 is used:

```nginx
upstream mcp_upstream {
    server fabric-prov-mcp:5000;  # container name + internal port
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name _;

    ssl_certificate     /etc/ssl/public.pem;
    ssl_certificate_key /etc/ssl/private.pem;

    client_max_body_size 10m;

    # (Optional) basic health
    location = /healthz { return 200 "ok\n"; add_header Content-Type text/plain; }

    # FastMCP endpoints (examples)
    location /mcp {
        proxy_pass         http://mcp_upstream;
        proxy_http_version 1.1;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   Authorization $http_authorization;  # pass Bearer token
        proxy_buffering    off;
    }

    # OpenAPI/Docs (FastAPI)
    location /docs   { proxy_pass http://mcp_upstream/docs; }
    location /openapi.json { proxy_pass http://mcp_upstream/openapi.json; }
}
```

## Adding new tools

- Add your tool function to an existing module under `server/tools/` (or create a new one) and include it in that module’s `TOOLS` list.
- If you add a new module, import it in `server/tools/__init__.py` and append its `TOOLS` to `ALL_TOOLS`.
- `__main__.py` auto-registers everything in `ALL_TOOLS`, so no extra wiring is needed after export.

> The MCP server runs on port **5000** in the container (`mcp.run(transport="http", host=0.0.0.0, port=5000)`).

---

## Local run (no Docker)

Requires Python 3.13+ (compatible with 3.14).

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install uv
uv pip install -r requirements.txt
LOG_LEVEL=DEBUG PORT=5000 python __main__.py
```

Then put your reverse proxy in front (or hit it directly if exposed).

---

## Using from MCP clients

### VS Code (`.mcp.json`)

```json
{
	"servers": {
		"fabric-api": {
			"type": "http",
			"url": "https://alpha-5.fabric-testbed.net/mcp",
			"headers": {
				"Authorization": "Bearer ${input:fabric-token}"
			},
		}
	},
	"inputs": [
		    {
      "type": "promptString",
      "id": "fabric-token",
      "description": "Enter your FABRIC token",
      "password": true
    }
    ]
}
```

### Claude Desktop (mcp-remote)

```json
{
  "mcpServers": {
    "fabric-api": {
      "command": "npx",
      "args": ["mcp-remote", "https://alpha-5.fabric-testbed/mcp",
        "--header", "Authorization: Bearer ${FABRIC_ID_TOKEN}"
      ],
      "env": { "FABRIC_ID_TOKEN": "" }
    }
  }
}
```

> You can point `prompt` at `server/system.md` to enforce your system prompt.

---

## Quick tool examples

**Query hosts at UCSD with GPUs, sorted by free cores**

```jsonc
{
  "tool": "query-hosts",
  "params": {
    "filters": "lambda r: r.get('site') == 'UCSD' and any('GPU' in c for c in r.get('components', {}).keys())",
    "sort": { "field": "cores_available", "direction": "desc" },
    "limit": 100
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

**Valid component and network types**

- Component models: `GPU_TeslaT4`, `GPU_RTX6000`, `GPU_A40`, `GPU_A30`, `NIC_Basic`, `NIC_ConnectX_5`, `NIC_ConnectX_6`, `NIC_ConnectX_7_100`, `NVME_P4510`, `FPGA_Xilinx_U280`
- L2 network types: `L2PTP` (requires SmartNIC, auto-added), `L2STS`, `L2Bridge` (single-site only)
- L3 network types: `FABNetv4`, `FABNetv6`, `IPv4`, `IPv6`, `FABNetv4Ext`, `FABNetv6Ext`, `IPv4Ext`, `IPv6Ext`
- Generic shorthand: `L2` (auto-selects `L2Bridge` or `L2STS` based on topology)
- If `type` is omitted: single-site defaults to `L2Bridge`, multi-site defaults to per-node `FABNetv4`

---

## System prompt

Your `server/system.md` is exposed to clients via:

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

## Security notes

* Tokens are accepted only via **Authorization header**; they are **not stored**.
* Do not print tokens in logs. (Server code avoids this.)
* Terminate TLS at NGINX; keep the MCP service on an internal network.
* Rotate TLS certs and restrict `client_max_body_size` if desired.

---

## License

[MIT](./LICENSE).
