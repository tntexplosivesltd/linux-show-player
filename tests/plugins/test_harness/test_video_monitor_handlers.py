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

"""Unit tests for the video_monitor.* RPC handlers.

video_monitor.toggle triggers the Tools > Video Monitor menu action, the
same path a user takes, and like every widget touch it must run on the
main thread.
"""

from types import SimpleNamespace

import pytest

from lisp.plugins.gst_backend.gst_backend import GstBackend
from lisp.plugins.test_harness import handlers
from lisp.plugins.test_harness.dispatcher import Dispatcher


class FakeMonitor:
    def __init__(self):
        self.visible = False

    def isVisible(self):
        return self.visible


@pytest.fixture
def harness(monkeypatch):
    invoked = []

    def fake_invoke(fn, timeout=10.0):
        invoked.append(fn)
        return fn()

    monkeypatch.setattr(handlers, "invoke_on_main_thread", fake_invoke)

    monitor = FakeMonitor()
    monkeypatch.setattr(GstBackend, "_monitor_window", monitor)

    def trigger():
        monitor.visible = not monitor.visible

    plugin = SimpleNamespace(
        _monitor_action=SimpleNamespace(trigger=trigger)
    )
    monkeypatch.setattr("lisp.plugins.get_plugin", lambda name: plugin)

    d = Dispatcher()
    handlers.register_all(d, SimpleNamespace(), signal_manager=None)
    return d, invoked, monitor


def _call(dispatcher, method):
    return dispatcher.dispatch({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": {},
    })


def test_toggle_triggers_menu_action_on_main_thread(harness):
    d, invoked, monitor = harness

    resp = _call(d, "video_monitor.toggle")

    assert invoked, "toggle must touch the window via invoke_on_main_thread"
    assert monitor.visible is True
    assert resp["result"] == {"visible": True}

    resp = _call(d, "video_monitor.toggle")
    assert resp["result"] == {"visible": False}


def test_state_reports_visibility_on_main_thread(harness):
    d, invoked, monitor = harness
    monitor.visible = True

    resp = _call(d, "video_monitor.state")

    assert invoked, "state must read the widget on the main thread"
    assert resp["result"] == {"exists": True, "visible": True}


def test_state_without_monitor_window(harness, monkeypatch):
    d, _invoked, _monitor = harness
    monkeypatch.setattr(GstBackend, "_monitor_window", None)

    resp = _call(d, "video_monitor.state")

    assert resp["result"] == {"exists": False, "visible": False}
