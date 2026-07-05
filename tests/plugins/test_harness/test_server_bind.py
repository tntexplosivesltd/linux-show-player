import socket

from lisp.plugins.test_harness.server import JsonRpcServer


def test_falls_back_when_desired_port_busy():
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", 0))
    busy_port = blocker.getsockname()[1]
    blocker.listen(1)
    try:
        srv = JsonRpcServer("127.0.0.1", busy_port, dispatcher=None)
        try:
            bound = srv.server_address[1]
            assert bound != 0
            assert bound != busy_port
        finally:
            srv.server_close()
    finally:
        blocker.close()


def test_binds_requested_port_when_free():
    srv = JsonRpcServer("127.0.0.1", 0, dispatcher=None)
    try:
        assert srv.server_address[1] != 0  # OS assigned a real port
    finally:
        srv.server_close()
