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

import logging

logger = logging.getLogger(__name__)

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
APP_ERROR = -32000
TIMEOUT_ERROR = -32001


class AppError(Exception):
    """Application-level error (e.g. cue not found, no session)."""
    pass


class Dispatcher:
    """JSON-RPC 2.0 method dispatcher."""

    def __init__(self):
        self._methods = {}

    def register(self, method_name, handler):
        """Register a handler function for a JSON-RPC method.

        :param method_name: Dot-notation method name (e.g. 'cue.list')
        :param handler: Callable that takes params dict and returns result
        """
        self._methods[method_name] = handler

    def dispatch(self, request):
        """Dispatch a JSON-RPC 2.0 request and return a response dict.

        Returns None for notifications (requests without an 'id' field),
        per JSON-RPC 2.0 spec.

        :param request: Parsed JSON-RPC request dict
        :returns: JSON-RPC 2.0 response dict, or None for notifications
        """
        is_notification = "id" not in request
        req_id = request.get("id")

        # Validate JSON-RPC envelope
        if request.get("jsonrpc") != "2.0":
            return _error_response(
                req_id, INVALID_REQUEST, "Invalid JSON-RPC version"
            )

        method = request.get("method")
        if not isinstance(method, str):
            return _error_response(
                req_id, INVALID_REQUEST, "Missing or invalid method"
            )

        handler = self._methods.get(method)
        if handler is None:
            return _error_response(
                req_id, METHOD_NOT_FOUND, f"Method not found: {method}"
            )

        params = request.get("params", {})

        try:
            result = handler(params)
            # Notifications must not receive a response
            if is_notification:
                return None
            return {
                "jsonrpc": "2.0",
                "result": result,
                "id": req_id,
            }
        except AppError as e:
            if is_notification:
                return None
            return _error_response(req_id, APP_ERROR, str(e))
        except TimeoutError as e:
            if is_notification:
                return None
            return _error_response(
                req_id, TIMEOUT_ERROR, str(e) or "Operation timed out"
            )
        except TypeError as e:
            if is_notification:
                return None
            return _error_response(req_id, INVALID_PARAMS, str(e))
        except Exception as e:
            logger.exception(f"Internal error handling {method}")
            if is_notification:
                return None
            return _error_response(req_id, INTERNAL_ERROR, str(e))

    def list_methods(self):
        """Return sorted list of registered method names."""
        return sorted(self._methods.keys())


def _error_response(req_id, code, message):
    return {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "id": req_id,
    }
