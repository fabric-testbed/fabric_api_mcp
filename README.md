# FABRIC Provisioning MCP Server

A production-ready **Model Context Protocol (MCP)** server that exposes **FABRIC Testbed provisioning** and inventory queries through `fabric_manager_v2`, designed for secure, token-based use by LLM clients (ChatGPT MCP, VS Code, Claude Desktop, etc.).

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
- `create-slice` — create a slice from a serialized graph + SSH keys -- Not fully implemented
- `modify-slice` — modify an existing slice  -- Not fully implemented
- `accept-modify` — accept the last modify  -- Not fully implemented
- `renew-slice` — renew slice by `lease_end_time`
- `delete-slice` — delete a slice (by ID)
- `resources` — advertised resources (optionally filtered)
- `poa-create` — perform POA ops (e.g., `cpuinfo`, `reboot`, `addkey`)   -- Not fully implemented
- `poa-get` — POA status lookup  -- Not fully implemented

> All tools expect JSON params and return JSON.

---

## Authentication

Every MCP call **must include** a FABRIC ID token:

```

Authorization: Bearer <FABRIC_ID_TOKEN>

```

Obtain tokens via the FABRIC Portal → **Profile → Access Tokens** (the token JSON contains `id_token`).

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

- Access logs include a per-request **x-request-id** for tracing
- Optional **ResourceCache**: background refresher for fast `query-*` responses

---

## Repo layout 

```

.
├─ server/
│  ├─ server.py              # <— Your MCP server (provided)
│  ├─ resources_cache.py     # cache implementation (used by server.py)
│  ├─ system.md              # system prompt served via @mcp.prompt("fabric-system")
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

> The MCP server runs on port **5000** in the container (`mcp.run(transport="http", host=0.0.0.0, port=5000)`).

---

## Local run (no Docker)

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
LOG_LEVEL=DEBUG PORT=5000 python server.py
```

Then put your reverse proxy in front (or hit it directly if exposed).

---

## Using from MCP clients

### VS Code (`.mcp.json`)

```json
{
  "mcpServers": {
    "fabric-provisioning": {
      "type": "http",
      "url": "https://YOUR_HOST/mcp",
      "headers": {
        "Authorization": "Bearer ${FABRIC_ID_TOKEN}"
      },
      "prompt": "./system.md",
      "env": {
        "FABRIC_ID_TOKEN": ""
      }
    }
  }
}
```

### Claude Desktop (mcp-remote)

```json
{
  "mcpServers": {
    "fabric-provisioning-remote": {
      "command": "npx",
      "args": ["mcp-remote", "https://YOUR_HOST/mcp",
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
    "filters": { "site": {"eq": "UCSD"}, "name": {"icontains": "w"} },
    "sort": { "field": "cores_available", "direction": "desc" },
    "limit": 100
  }
}
```

**POA: reboot a node’s sliver**

```jsonc
{
  "tool": "poa-create",
  "params": {
    "sliver_id": "<SLIVER-UUID>",
    "operation": "reboot"
  }
}
```

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
