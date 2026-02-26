#!/usr/bin/env python3
"""Standalone script to call the build-slice MCP tool over HTTP."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

DEFAULT_TOKEN_JSON = Path.home() / "work" / "claude" / "id_token.json"
DEFAULT_URL = "http://localhost:8000/mcp"
DEFAULT_TIMEOUT_SECS = 60

DEFAULT_NODES = [
    {
        "name": "node-utah",
        "site": "UTAH",
        "cores": 2,
        "ram": 8,
        "disk": 10,
        "image": "default_rocky_8",
    }
]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"File not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}")


def _read_token(args: argparse.Namespace) -> str:
    if args.token:
        return args.token.strip()

    env_token = os.environ.get("FABRIC_ID_TOKEN")
    if env_token:
        return env_token.strip()

    token_json_path = Path(args.token_file) if args.token_file else Path(
        os.environ.get("FABRIC_TOKEN_JSON", str(DEFAULT_TOKEN_JSON))
    )

    token_payload = _load_json(token_json_path)
    token = token_payload.get("id_token")
    if not token:
        raise SystemExit(f"Could not find 'id_token' in {token_json_path}")
    return token


def _read_ssh_keys(args: argparse.Namespace) -> List[str]:
    keys: List[str] = []
    if args.ssh_key:
        keys.extend([k.strip() for k in args.ssh_key if k.strip()])

    if args.ssh_key_file:
        for path in args.ssh_key_file:
            key_path = Path(path).expanduser()
            try:
                key = key_path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                raise SystemExit(f"SSH key file not found: {key_path}")
            if key:
                keys.append(key)

    if not keys:
        default_key_path = Path.home() / ".ssh" / "id_rsa.pub"
        if default_key_path.exists():
            keys.append(default_key_path.read_text(encoding="utf-8").strip())

    return keys


def _jsonrpc_request(
    url: str,
    method: str,
    params: Optional[Dict[str, Any]],
    headers: Dict[str, str],
    timeout: int,
    request_id: Optional[int],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        payload["id"] = request_id
    if params is not None:
        payload["params"] = params

    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    try:
        response.raise_for_status()
    except requests.HTTPError:
        body = response.text.strip()
        raise SystemExit(f"HTTP {response.status_code}: {body or '<empty>'}")
    if not response.text:
        return {}
    try:
        return response.json()
    except json.JSONDecodeError:
        text = response.text.strip()
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type or text.startswith("event:"):
            # Parse first SSE data payload
            for line in text.splitlines():
                if line.startswith("data:"):
                    data = line[len("data:") :].strip()
                    if data:
                        try:
                            return json.loads(data)
                        except json.JSONDecodeError:
                            break
        raise SystemExit(f"Non-JSON response: {response.text}")


def _jsonrpc_request_with_headers(
    url: str,
    method: str,
    params: Optional[Dict[str, Any]],
    headers: Dict[str, str],
    timeout: int,
    request_id: Optional[int],
) -> tuple[Dict[str, Any], Dict[str, str]]:
    payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        payload["id"] = request_id
    if params is not None:
        payload["params"] = params

    response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    try:
        response.raise_for_status()
    except requests.HTTPError:
        body = response.text.strip()
        raise SystemExit(f"HTTP {response.status_code}: {body or '<empty>'}")

    if not response.text:
        return {}, dict(response.headers)

    try:
        return response.json(), dict(response.headers)
    except json.JSONDecodeError:
        text = response.text.strip()
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type or text.startswith("event:"):
            for line in text.splitlines():
                if line.startswith("data:"):
                    data = line[len("data:") :].strip()
                    if data:
                        try:
                            return json.loads(data), dict(response.headers)
                        except json.JSONDecodeError:
                            break
        raise SystemExit(f"Non-JSON response: {response.text}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Call build-slice over MCP HTTP.")
    parser.add_argument("--url", default=DEFAULT_URL, help="MCP HTTP endpoint")
    parser.add_argument("--token", help="FABRIC ID token (overrides env/file)")
    parser.add_argument(
        "--token-file",
        help="Path to JSON containing {'id_token': '...'} (default: $FABRIC_TOKEN_JSON)",
    )
    parser.add_argument("--name", help="Slice name (default: autogenerated)")
    parser.add_argument(
        "--ssh-key",
        action="append",
        help="SSH public key string (repeatable)",
    )
    parser.add_argument(
        "--ssh-key-file",
        action="append",
        help="Path to SSH public key file (repeatable)",
    )
    parser.add_argument("--nodes-file", help="Path to nodes JSON array")
    parser.add_argument("--networks-file", help="Path to networks JSON array")
    parser.add_argument("--lifetime", type=int, help="Slice lifetime in days")
    parser.add_argument(
        "--tool",
        default="build-slice",
        help="Tool name to call (default: build-slice)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually submit the slice (default is dry-run)",
    )
    parser.add_argument(
        "--skip-init",
        action="store_true",
        help="Skip MCP initialize/initialized handshake",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECS)
    parser.add_argument(
        "--accept",
        default="application/json, text/event-stream",
        help="Override Accept header",
    )
    parser.add_argument(
        "--content-type",
        default="application/json",
        help="Override Content-Type header",
    )

    args = parser.parse_args()

    token = _read_token(args)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": args.accept,
        "Content-Type": args.content_type,
    }

    name = args.name or f"mcp-build-slice-test-{int(time.time())}"
    ssh_keys = _read_ssh_keys(args)

    if args.nodes_file:
        nodes = _load_json(Path(args.nodes_file))
    else:
        nodes = DEFAULT_NODES

    networks = None
    if args.networks_file:
        networks = _load_json(Path(args.networks_file))

    params: Dict[str, Any] = {
        "name": name,
        "ssh_keys": ssh_keys,
        "nodes": nodes,
    }
    if networks is not None:
        params["networks"] = networks
    if args.lifetime is not None:
        params["lifetime"] = args.lifetime

    if not args.execute:
        print("Dry run only. Pass --execute to submit the slice.")
        print(json.dumps(params, indent=2))
        return 0

    if not args.skip_init:
        init_result, init_headers = _jsonrpc_request_with_headers(
            args.url,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "clientInfo": {"name": "build-slice-test", "version": "0.1.0"},
                "capabilities": {},
            },
            headers=headers,
            timeout=args.timeout,
            request_id=1,
        )
        session_id = (
            init_headers.get("mcp-session-id")
            or init_headers.get("Mcp-Session-Id")
            or init_headers.get("mcp-session")
        )
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        _jsonrpc_request(
            args.url,
            "initialized",
            {},
            headers=headers,
            timeout=args.timeout,
            request_id=None,
        )
        try:
            tool_list = _jsonrpc_request(
                args.url,
                "tools/list",
                {},
                headers=headers,
                timeout=args.timeout,
                request_id=3,
            )
            tool_names = [
                t.get("name")
                for t in tool_list.get("result", {}).get("tools", [])
                if isinstance(t, dict)
            ]
            if args.tool not in tool_names:
                if "build_slice" in tool_names:
                    args.tool = "build_slice"
        except SystemExit:
            pass

    result = _jsonrpc_request(
        args.url,
        "tools/call",
        {"name": args.tool, "arguments": params},
        headers=headers,
        timeout=args.timeout,
        request_id=2,
    )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
