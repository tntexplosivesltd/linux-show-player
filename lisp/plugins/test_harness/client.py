#!/usr/bin/env python3
"""Standalone CLI client for the LiSP Test Harness plugin.

Zero LiSP dependencies — uses only Python stdlib.

Usage:
    python client.py [--host HOST] [--port PORT] <method> [params_json]

Examples:
    python client.py ping
    python client.py cue.list
    python client.py cue.get '{"id": "abc-123"}'
    python client.py session.new '{"layout_type": "ListLayout"}'
    python client.py signals.subscribe '{"signal": "cue_model.item_added"}'
    python client.py signals.wait_for '{"subscription_id": "...", "timeout": 5}'

Exit codes:
    0 - Success (result JSON printed to stdout)
    1 - JSON-RPC error (error JSON printed to stderr)
    2 - Transport/connection error (message printed to stderr)
"""

import argparse
import json
import os
import socket
import sys

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8070
SOCKET_TIMEOUT = 30.0

PORTFILE_NAME = ".lisp-test-harness-port"
PORTFILE_ENV = "LISP_TEST_HARNESS_PORTFILE"


def _find_repo_root(anchor):
    path = os.path.abspath(anchor)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    while True:
        if os.path.isfile(os.path.join(path, "pyproject.toml")):
            return path
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def _read_portfile(anchor):
    """Return the port from env/repo-root discovery file, or None.

    Mirrors ``lisp.plugins.test_harness.portfile`` deliberately to keep
    this CLI stdlib-only. One intentional difference: with no repo root
    found this returns None (→ DEFAULT_PORT), whereas the server-side
    ``resolve_portfile_path`` falls back to cwd — a reader has no port to
    guess, so defaulting is correct here. Both anchors live inside the
    repo in practice, so this branch is unreachable in normal use.
    """
    override = os.environ.get(PORTFILE_ENV)
    if override:
        path = override
    else:
        root = _find_repo_root(anchor)
        if root is None:
            return None
        path = os.path.join(root, PORTFILE_NAME)
    try:
        with open(path) as f:
            port = int(f.read().strip())
    except (OSError, ValueError):
        return None
    return port if 0 <= port <= 65535 else None


def resolve_port(explicit, anchor=__file__):
    """Explicit flag > discovery file (env/repo-root) > default."""
    if explicit is not None:
        return explicit
    found = _read_portfile(anchor)
    return found if found is not None else DEFAULT_PORT


def send_request(host, port, method, params=None):
    """Send a JSON-RPC 2.0 request and return the response."""
    request = {
        "jsonrpc": "2.0",
        "method": method,
        "id": 1,
    }
    if params is not None:
        request["params"] = params

    request_line = json.dumps(request) + "\n"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)

    try:
        sock.connect((host, port))
        sock.sendall(request_line.encode("utf-8"))

        # Read response (newline-delimited)
        data = b""
        while b"\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk

        if not data:
            raise ConnectionError("No response from server")

        response_line = data.split(b"\n", 1)[0]
        return json.loads(response_line)
    finally:
        sock.close()


def main():
    parser = argparse.ArgumentParser(
        description="LiSP Test Harness CLI Client"
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST,
        help=f"Server host (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help=f"Server port (default: auto-detect, else {DEFAULT_PORT})"
    )
    parser.add_argument(
        "method",
        help="JSON-RPC method name (e.g. ping, cue.list)"
    )
    parser.add_argument(
        "params", nargs="?", default=None,
        help="JSON-encoded params (e.g. '{\"id\": \"abc\"}')"
    )

    args = parser.parse_args()
    port = resolve_port(args.port)

    # Parse params JSON if provided
    params = None
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as e:
            print(f"Invalid params JSON: {e}", file=sys.stderr)
            sys.exit(2)

    try:
        response = send_request(args.host, port, args.method, params)
    except ConnectionRefusedError:
        print(
            f"Connection refused: {args.host}:{port}\n"
            f"Is the Test Harness plugin enabled and LiSP running?",
            file=sys.stderr,
        )
        sys.exit(2)
    except socket.timeout:
        print(
            f"Connection timed out: {args.host}:{port}",
            file=sys.stderr,
        )
        sys.exit(2)
    except ConnectionError as e:
        print(f"Connection error: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    if "error" in response:
        error = response["error"]
        print(
            json.dumps(error, indent=2),
            file=sys.stderr,
        )
        sys.exit(1)

    result = response.get("result")
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
