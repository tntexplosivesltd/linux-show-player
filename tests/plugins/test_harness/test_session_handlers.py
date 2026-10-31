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

"""Unit tests for the session.info RPC handler.

``Application.__load_from_file`` runs synchronously on the Qt main
thread: it creates the Session (``app.session`` becomes non-None), adds
every cue, then emits ``session_loaded`` whose handlers (e.g. the
shuffle-on-load reorder) run inline. The RPC server runs on its own
thread, so answering session.info there reports ``has_session`` at the
*start* of that load, and callers race the rest of it. Answering on the
main thread makes ``has_session=True`` mean the load fully finished.
"""

from types import SimpleNamespace

from lisp.plugins.test_harness import handlers
from lisp.plugins.test_harness.dispatcher import Dispatcher


def _call(dispatcher, method, params=None):
    return dispatcher.dispatch({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    })


def _dispatcher(app):
    d = Dispatcher()
    handlers.register_all(d, app, signal_manager=None)
    return d


def test_session_info_is_answered_on_main_thread(monkeypatch):
    invoked = []

    def fake_invoke(fn, timeout=10.0):
        invoked.append(fn)
        return fn()

    monkeypatch.setattr(handlers, "invoke_on_main_thread", fake_invoke)
    app = SimpleNamespace(
        session=SimpleNamespace(session_file="/x.lsp"),
        layout=SimpleNamespace(),
    )

    resp = _call(_dispatcher(app), "session.info")

    assert invoked, "session.info must run via invoke_on_main_thread"
    assert resp["result"]["has_session"] is True
    assert resp["result"]["session_file"] == "/x.lsp"


def test_session_info_without_session(monkeypatch):
    monkeypatch.setattr(
        handlers, "invoke_on_main_thread", lambda fn, timeout=10.0: fn()
    )
    app = SimpleNamespace(session=None)

    resp = _call(_dispatcher(app), "session.info")

    assert resp["result"] == {"has_session": False}
