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

"""Unit tests for the layout.find / layout.find_jump RPC handlers.

These focus on request-parameter validation: a malformed type must be
rejected with a clean AppError (-32000) rather than exploding with a
TypeError deep inside the Qt main-thread callable.
"""

from types import SimpleNamespace

from lisp.plugins.list_layout.layout import ListLayout
from lisp.plugins.test_harness.dispatcher import Dispatcher
from lisp.plugins.test_harness.handlers import register_all


def _make_app():
    # A session that is not None satisfies _require_session; a ListLayout
    # instance (built without heavy __init__) satisfies _require_list_layout.
    return SimpleNamespace(
        session=SimpleNamespace(),
        layout=ListLayout.__new__(ListLayout),
    )


def _dispatcher():
    d = Dispatcher()
    register_all(d, _make_app(), signal_manager=None)
    return d


def _call(dispatcher, method, params):
    return dispatcher.dispatch({
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    })


def test_find_rejects_non_string_text():
    resp = _call(_dispatcher(), "layout.find", {"text": 123})
    assert "error" in resp
    assert resp["error"]["code"] == -32000
    assert "text" in resp["error"]["message"]


def test_find_rejects_non_string_color():
    resp = _call(_dispatcher(), "layout.find", {"color": ["red"]})
    assert "error" in resp
    assert resp["error"]["code"] == -32000
    assert "color" in resp["error"]["message"]


def test_find_jump_rejects_non_int_step():
    resp = _call(_dispatcher(), "layout.find_jump", {"step": "next"})
    assert "error" in resp
    assert resp["error"]["code"] == -32000
    assert "step" in resp["error"]["message"]
