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

"""Unit tests for the TestHarness plugin's portfile lifecycle.

The plugin's integration glue — write the discovery file with the real
bound port on __init__, remove it on finalize(), and stop the just-
started server thread if publishing the port fails — is otherwise only
exercised by a live E2E run. These tests stub the plugin's collaborators
(Qt invoker, signal manager, dispatcher, server thread) so the portfile
logic can be verified in isolation, with no real socket or QApplication.
"""

from types import SimpleNamespace

import pytest

from lisp.plugins.test_harness import portfile
from lisp.plugins.test_harness import test_harness as th_mod

# Reference the plugin via the module (not a top-level import) so pytest
# doesn't try to collect the ``TestHarness`` *plugin* class as a test.
Harness = th_mod.TestHarness

BOUND_PORT = 54321


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    """Stub TestHarness collaborators; portfile logic stays real."""
    created = []

    class FakeServerThread:
        def __init__(self, host, port, dispatcher):
            self.server = SimpleNamespace(server_address=(host, BOUND_PORT))
            self.started = False
            self.stopped = False
            created.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    monkeypatch.setattr(th_mod, "init_invoker", lambda: None)
    monkeypatch.setattr(
        th_mod,
        "SignalManager",
        lambda app, max_buffer: SimpleNamespace(
            unsubscribe_all=lambda: None
        ),
    )
    monkeypatch.setattr(th_mod, "Dispatcher", lambda: SimpleNamespace())
    monkeypatch.setattr(th_mod, "register_all", lambda d, app, sm: None)
    monkeypatch.setattr(th_mod, "ServerThread", FakeServerThread)
    monkeypatch.setattr(
        Harness,
        "Config",
        {"host": "127.0.0.1", "port": 8070, "maxEventBuffer": 100},
    )

    pf = str(tmp_path / ".lisp-test-harness-port")
    monkeypatch.setattr(
        portfile, "resolve_portfile_path", lambda anchor: pf
    )
    return SimpleNamespace(portfile=pf, created=created)


def test_portfile_written_with_bound_port_and_removed(stubbed):
    harness = Harness(SimpleNamespace())
    try:
        # __init__ published the actual bound port, not Config["port"].
        assert portfile.read_port(stubbed.portfile) == BOUND_PORT
        assert harness.server_thread.started
    finally:
        harness.finalize()

    assert harness.server_thread.stopped
    assert portfile.read_port(stubbed.portfile) is None


def test_init_stops_thread_when_port_publish_fails(stubbed, monkeypatch):
    def boom(path, port):
        raise OSError("read-only worktree")

    monkeypatch.setattr(portfile, "write_port", boom)

    with pytest.raises(OSError):
        Harness(SimpleNamespace())

    # The started server thread must be stopped on the failure path so
    # no bound, listening socket is orphaned.
    assert stubbed.created, "server thread was never constructed"
    thread = stubbed.created[-1]
    assert thread.started
    assert thread.stopped
    # No portfile should linger from the failed init.
    assert portfile.read_port(stubbed.portfile) is None
