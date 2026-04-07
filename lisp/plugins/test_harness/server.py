# This file is part of Linux Show Player
#
# Copyright 2024 Linux Show Player Contributors
#
# Linux Show Player is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Linux Show Player is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Linux Show Player.  If not, see <http://www.gnu.org/licenses/>.

import json
import logging
import socketserver
from threading import Thread

from lisp.plugins.test_harness.dispatcher import PARSE_ERROR
from lisp.plugins.test_harness.serializers import LispJsonEncoder

logger = logging.getLogger(__name__)


class JsonRpcServer(socketserver.TCPServer):
    """TCP server that dispatches newline-delimited JSON-RPC 2.0 requests."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, host, port, dispatcher):
        self.dispatcher = dispatcher
        super().__init__((host, port), JsonRpcHandler)


class JsonRpcHandler(socketserver.StreamRequestHandler):
    """Handles a single persistent TCP connection.

    Reads newline-delimited JSON-RPC requests in a loop,
    dispatches each to the server's dispatcher, and writes
    back newline-delimited JSON responses.
    """

    def handle(self):
        logger.debug(
            "Test harness client connected from %s", self.client_address
        )
        try:
            for line in self.rfile:
                line = line.strip()
                if not line:
                    continue

                try:
                    request = json.loads(line)
                except json.JSONDecodeError as e:
                    response = {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": PARSE_ERROR,
                            "message": f"Parse error: {e}",
                        },
                        "id": None,
                    }
                else:
                    response = self.server.dispatcher.dispatch(request)

                # None means notification — no response per JSON-RPC 2.0
                if response is not None:
                    response_bytes = (
                        json.dumps(response, cls=LispJsonEncoder)
                        .encode("utf-8") + b"\n"
                    )
                    self.wfile.write(response_bytes)
                    self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            logger.debug(
                "Test harness client disconnected: %s", self.client_address
            )
        except Exception:
            logger.exception("Error in test harness connection handler")


class ServerThread(Thread):
    """Runs the JSON-RPC TCP server in a daemon thread."""

    def __init__(self, host, port, dispatcher):
        super().__init__(daemon=True)
        self.server = JsonRpcServer(host, port, dispatcher)

    def run(self):
        logger.info(
            "Test harness serving on %s:%d",
            self.server.server_address[0],
            self.server.server_address[1],
        )
        self.server.serve_forever()
        logger.info("Test harness server stopped")

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.join()
