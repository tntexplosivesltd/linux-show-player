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
import socket
import sys

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8070
SOCKET_TIMEOUT = 30.0


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
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Server port (default: {DEFAULT_PORT})"
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

    # Parse params JSON if provided
    params = None
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as e:
            print(f"Invalid params JSON: {e}", file=sys.stderr)
            sys.exit(2)

    try:
        response = send_request(args.host, args.port, args.method, params)
    except ConnectionRefusedError:
        print(
            f"Connection refused: {args.host}:{args.port}\n"
            f"Is the Test Harness plugin enabled and LiSP running?",
            file=sys.stderr,
        )
        sys.exit(2)
    except socket.timeout:
        print(
            f"Connection timed out: {args.host}:{args.port}",
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
