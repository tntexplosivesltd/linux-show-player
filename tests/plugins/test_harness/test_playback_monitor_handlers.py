# This file is part of Linux Show Player
#
# Copyright 2026 Francesco Ceruti <ceppofrancy@gmail.com>
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

"""Unit tests for the playback_monitor.* RPC handlers.

playback_monitor.toggle creates the monitor's QWidget on first use. Run
on the RPC server thread, that widget belongs to a thread with no Qt
event loop: its labels' text still updates (the CueTime slot runs on the
main thread), but its paint events are never processed, so the window
on screen stays frozen on its first frame while the harness -- which
reads label text -- reports it counting. Widgets must be created and
read on the main thread.
"""

from types import SimpleNamespace

import pytest

from lisp.plugins.test_harness import handlers
from lisp.plugins.test_harness.dispatcher import Dispatcher


@pytest.fixture
def harness(monkeypatch):
    invoked = []

    def fake_invoke(fn, timeout=10.0):
        invoked.append(fn)
        return fn()

    monkeypatch.setattr(handlers, "invoke_on_main_thread", fake_invoke)

    window = SimpleNamespace(
        isVisible=lambda: True,
        _tracked_cue=None,
        _name_label=SimpleNamespace(text=lambda: "—"),
        elapsed_text="00:00",
        remaining_text="00:00",
    )
    plugin = SimpleNamespace(_window=None)

    def toggle():
        plugin._window = window

    plugin._toggle_window = toggle
    monkeypatch.setattr(
        "lisp.plugins.get_plugin", lambda name: plugin
    )

    d = Dispatcher()
    handlers.register_all(d, SimpleNamespace(), signal_manager=None)
    return d, invoked, plugin


def _call(dispatcher, method):
    return dispatcher.dispatch({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": {},
    })


def test_toggle_runs_on_main_thread(harness):
    d, invoked, plugin = harness

    resp = _call(d, "playback_monitor.toggle")

    assert invoked, "toggle must create the window via invoke_on_main_thread"
    assert plugin._window is not None
    assert resp["result"]["visible"] is True


def test_state_runs_on_main_thread(harness):
    d, invoked, plugin = harness
    plugin._toggle_window()

    resp = _call(d, "playback_monitor.state")

    assert invoked, "state must read widget text on the main thread"
    assert resp["result"]["elapsed"] == "00:00"
