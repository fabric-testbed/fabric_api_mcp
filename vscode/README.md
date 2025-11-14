# Set up and use an HTTP-streamable MCP server in VS Code (with a custom Chat mode)

## Table of Contents
- [Set up and use an HTTP-streamable MCP server in VS Code (with a custom Chat mode)](#set-up-and-use-an-http-streamable-mcp-server-in-vs-code-with-a-custom-chat-mode)
  - [Prerequisites](#prerequisites)
  - [Setup Options](#setup-options)
    - [Option A: Remote HTTP Server (Production)](#option-a-remote-http-server-production)
    - [Option B: Local Docker Server (Development)](#option-b-local-docker-server-development)
  - [1) Create `.vscode/mcp.json` and add your server](#1-create-vscodemcpjson-and-add-your-server)
  - [2) Start the MCP server from VS Code](#2-start-the-mcp-server-from-vs-code)
  - [3) Create a custom Chat mode and add your System prompt](#3-create-a-custom-chat-mode-and-add-your-system-prompt)
  - [4) Use your custom mode with the running MCP server](#4-use-your-custom-mode-with-the-running-mcp-server)
  - [Example "first query" ideas](#example-first-query-ideas)

## Prerequisites

* VS Code (latest)
* The MCP-capable chat extension enabled (e.g., GitHub Copilot Chat with MCP support)

**For Remote Setup:**
* Your MCP server reachable over HTTPS
* Your per-user token (FABRIC token) handy. You can generate a new FABRIC token by visiting [https://cm.fabric-testbed.net/](https://cm.fabric-testbed.net/).

---

## Setup Options

You can connect to the FABRIC Reports MCP server in two ways:

### Option A: Remote HTTP Server (Production)

Use the **`mcp.json`** configuration to connect to the production FABRIC Reports server at `https://reports.fabric-testbed.net/mcp`. This is the recommended approach for regular usage.

**Pros:**
* No local setup required
* Always uses the latest production version
* No need to run Docker locally

**Cons:**
* Requires network connectivity
* Needs a valid FABRIC token

---

## 1) Create `.vscode/mcp.json` and add your server

In your workspace, create the file `.vscode/mcp.json`:

* **For remote setup**: Copy the provided `mcp.json` file, which connects to the production server. The token is prompted once per VS Code session.
---

## 2) Start the MCP server from VS Code

* Open `.vscode/mcp.json` in the editor.
* Click the **Start** (▶︎) button that appears for your server:
  * `fabric-api` (for remote HTTP setup)
* Confirm it shows as **running** (you'll typically see status in the MCP panel or the editor UI).

---

## 3) Create a custom Chat mode and add your System prompt

* Open the Chat view in VS Code.
* Go to **Configure Modes** → **Create new custom mode chat file**.
* In the new mode file (it’s JSON), give it a name and paste the contents of `fabric-api.chatmode.md`

Save the file.

---

## 4) Use your custom mode with the running MCP server

* In the Chat window, select the new mode (e.g., **fabric-api**) from the mode dropdown.
* Ensure your MCP server shows up as connected:
  * `fabric-api`
  * You'll see available tools in the Chat sidebar/panel when the server is active
* Start asking questions—your requests will flow through the custom mode + MCP tools.

---

## Example “first query” ideas

* “List all active slivers.”
* “Show slice utilization by site.”
* “Summarize sliver states with counts per state.”

---