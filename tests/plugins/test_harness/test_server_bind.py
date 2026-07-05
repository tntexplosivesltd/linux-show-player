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
    # Discover a currently-free, specific port, then release it so the
    # server can claim it — exercises the common single-worktree case
    # (a real port like 8070 is free) rather than the port-0 fallback.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()

    srv = JsonRpcServer("127.0.0.1", free_port, dispatcher=None)
    try:
        # The requested port was free, so the fallback must NOT fire.
        assert srv.server_address[1] == free_port
    finally:
        srv.server_close()
