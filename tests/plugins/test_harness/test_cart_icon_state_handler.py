# This file is part of Linux Show Player
#
# Copyright 2026
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

"""``cart.cell_icon_state`` must judge a disabled cell independently
of the widget's own dim-icon cache (M59).

If ``expected`` is read back out of the cache that produced the cell's
icon, a wrong cache entry makes ``matches`` true by construction."""

from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPixmap

from lisp.cues.cue import Cue
from lisp.plugins.cart_layout.cue_widget import (
    CueWidget,
    _DIM_ICON_SIZE,
    _dim_icon,
)
from lisp.plugins.cart_layout.layout import CartLayout
from lisp.plugins.test_harness import qt_invoke
from lisp.plugins.test_harness.dispatcher import Dispatcher
from lisp.plugins.test_harness.handlers import register_all
from lisp.ui.icons import IconTheme

_ICON = "media-playback-start-cart"


def _solid_icon(color):
    pixmap = QPixmap(QSize(_DIM_ICON_SIZE, _DIM_ICON_SIZE))
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


@pytest.fixture
def cart(qapp, mock_app, monkeypatch):
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("lisp")
    red = _solid_icon(Qt.red)
    real_get = IconTheme.get

    def fake_get(name):
        return red if name == _ICON else real_get(name)

    monkeypatch.setattr(IconTheme, "get", fake_get)
    # Handlers run on the test (= main) thread, so invoke_on_main_thread
    # calls straight through; it only needs an invoker to exist.
    monkeypatch.setattr(qt_invoke, "_invoker", object())

    cue = Cue(mock_app)
    cue.icon = "media-playback-start"
    cue.disabled = True
    widget = CueWidget(cue)

    layout = CartLayout.__new__(CartLayout)
    page = SimpleNamespace(widgets=lambda: [widget])
    layout._cart_view = SimpleNamespace(pages=lambda: [page])
    app = SimpleNamespace(
        session=SimpleNamespace(),
        layout=layout,
        cue_model=SimpleNamespace(
            get=lambda cid: cue if cid == cue.id else None
        ),
    )
    dispatcher = Dispatcher()
    register_all(dispatcher, app, signal_manager=None)
    return SimpleNamespace(
        cue=cue, widget=widget, red=red, dispatcher=dispatcher
    )


def _state(cart):
    resp = cart.dispatcher.dispatch({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "cart.cell_icon_state",
        "params": {"cue_id": cart.cue.id},
    })
    assert "error" not in resp, resp
    return resp["result"]


def test_disabled_cell_with_correct_dim_icon_matches(cart):
    state = _state(cart)
    assert state["effective_disabled"] is True
    assert state["matches"] is True


def test_disabled_cell_with_wrong_dim_icon_does_not_match(cart):
    """Poison the widget's cache so the cell renders the dim copy of
    a *different* icon. The harness must notice."""
    blue_dim = _dim_icon(_solid_icon(Qt.blue))
    cart.widget._dimIconCache = (cart.red, blue_dim)
    cart.widget._updateStyle()
    assert cart.widget.nameButton._icon is blue_dim

    assert _state(cart)["matches"] is False


def test_disabled_cell_showing_undimmed_icon_does_not_match(cart):
    cart.widget.nameButton.setIcon(cart.red)
    assert _state(cart)["matches"] is False
