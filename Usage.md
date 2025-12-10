# Usage

Quick steps for running the FABRIC MCP server in HTTP mode (typical for containers/reverse proxies) or STDIO mode (direct MCP client integration), plus sample MCP client configs (VS Code, Claude Desktop/Chatbox).

## Prerequisites

- Python 3.11+
- Install dependencies: `pip install -r server/requirements.txt`
- Set FABRIC API host env vars as needed (defaults are production); auth uses Bearer FABRIC ID tokens supplied by the client.

## HTTP mode (default)

Run from the repo root:

```bash
LOG_LEVEL=INFO PORT=5000 HOST=0.0.0.0 python -m server
```

Notes:
- Logs go to stdout; configure `LOG_FORMAT=json` if desired.
- Health/HTTP endpoints are served by FastAPI inside FastMCP.
- Docker: `docker compose up -d mcp-server` builds/runs the same HTTP transport.

### Client config (HTTP)

- **VS Code (MCP extension)** – in `settings.json`:
  ```json
  {
    "mcp.servers": {
      "fabric-mcp": {
        "url": "http://localhost:5000/mcp"
      }
    }
  }
  ```
- **Claude Desktop / Chatbox** – add an HTTP server entry pointing to `http://localhost:5000/mcp`.

Ensure your MCP client sends `Authorization: Bearer <id_token>` in headers for tool calls.

### Using the system prompt

The server exposes the prompt in `server/system.md` as MCP prompt `fabric-system`. In clients that support MCP prompts:
- VS Code MCP extension: use `@prompt fabric-system` (if supported) or fetch via MCP prompt list.
- Claude Desktop/Chatbox: run the MCP prompt named `fabric-system` to load the guidance text.

## STDIO mode

Run from the repo root to expose MCP over stdio (for local MCP clients):

```bash
LOG_LEVEL=INFO python - <<'PY'
from server.__main__ import mcp  # loads config, middleware, tools, cache setup
mcp.run(transport="stdio")
PY
```

Notes:
- STDIO mode still requires clients to send `Authorization: Bearer <id_token>` in request headers.
- You can change log settings via env (e.g., `LOG_FORMAT=json`).
- Cache/background setup runs on import, so the behavior matches the HTTP entrypoint.

### Client config (STDIO)

- **VS Code (MCP extension)** – in `settings.json`:
  ```json
  {
    "mcp.servers": {
      "fabric-mcp": {
        "command": "python",
        "args": ["-m", "server"]
      }
    }
  }
  ```
- **Claude Desktop / Chatbox** – add a stdio server entry with `command: "python"` and `args: ["-m", "server"]`.
