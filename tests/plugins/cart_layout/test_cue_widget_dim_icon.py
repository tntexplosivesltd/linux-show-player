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

"""Disabled cart cells show a dimmed copy of the cue's *current*
``-cart`` icon (H26).

The widget caches the dim variant so repeated ``_updateStyle`` calls
return the same QIcon. That cache must never hand back a dim variant
built from a different source icon — e.g. after an icon-theme switch
frees the old QIcon and CPython recycles its ``id()`` for the new one.
"""

import gc
import weakref

import pytest
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPixmap

from lisp.cues.cue import Cue
from lisp.plugins.cart_layout import cue_widget as cue_widget_mod
from lisp.plugins.cart_layout.cue_widget import (
    CueWidget,
    _DIM_ICON_SIZE,
    _dim_icon,
)
from lisp.ui.icons import IconTheme

_SIZE = QSize(_DIM_ICON_SIZE, _DIM_ICON_SIZE)


def _solid_icon(color):
    pixmap = QPixmap(_SIZE)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def _image(icon):
    return icon.pixmap(_SIZE).toImage()


class _FakeIconTheme:
    """Stands in for ``IconTheme.get``; ``icons`` maps name -> QIcon
    and can be swapped wholesale to mimic an icon-theme switch."""

    def __init__(self, icons, fallback):
        self.icons = icons
        self._fallback = fallback

    def get(self, name):
        if name.endswith("-cart"):
            return self.icons.get(name, QIcon())
        return self._fallback(name)


@pytest.fixture
def fake_theme(monkeypatch):
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("lisp")
    theme = _FakeIconTheme({}, IconTheme.get)
    monkeypatch.setattr(IconTheme, "get", theme.get)
    return theme


def _disabled_widget(mock_app, theme, icon_name="media-playback-start"):
    theme.icons[f"{icon_name}-cart"] = _solid_icon(Qt.red)
    cue = Cue(mock_app)
    cue.icon = icon_name
    cue.disabled = True
    widget = CueWidget(cue)
    return cue, widget


def test_disabled_cell_shows_dim_of_current_icon_after_id_reuse(
    qapp, mock_app, fake_theme, monkeypatch
):
    # Make every id() seen by the widget collide, as CPython does when
    # it reuses a freed QIcon's address for the next allocation.
    monkeypatch.setattr(
        cue_widget_mod, "id", lambda _obj: 0x1234, raising=False
    )
    cue, widget = _disabled_widget(mock_app, fake_theme)
    red_dim = _image(widget.nameButton._icon)
    assert red_dim == _image(_dim_icon(fake_theme.get(
        f"{cue.icon}-cart")))

    # Icon-theme switch: the red icon is replaced by a blue one.
    fake_theme.icons = {f"{cue.icon}-cart": _solid_icon(Qt.blue)}
    widget._updateStyle()

    shown = _image(widget.nameButton._icon)
    expected = _image(_dim_icon(fake_theme.get(f"{cue.icon}-cart")))
    assert shown != red_dim, "cell still shows the old theme's dim icon"
    assert shown == expected


def test_dim_variant_is_reused_for_the_same_source(
    qapp, mock_app, fake_theme
):
    _cue, widget = _disabled_widget(mock_app, fake_theme)
    first = widget.nameButton._icon
    widget._updateStyle()
    assert widget.nameButton._icon is first


def test_dim_cache_does_not_retain_old_source_icons(
    qapp, mock_app, fake_theme
):
    """Cycling a disabled cue through many icons must not pin every
    past dim copy (or its source icon) in memory."""
    cue, widget = _disabled_widget(mock_app, fake_theme)
    refs = []
    for i in range(5):
        name = f"icon-{i}"
        fake_theme.icons = {f"{name}-cart": _solid_icon(QColor(i, 0, 0))}
        cue.icon = name
        widget._updateStyle()
        refs.append(weakref.ref(fake_theme.icons[f"{name}-cart"]))
        refs.append(weakref.ref(widget.nameButton._icon))

    fake_theme.icons = {}
    gc.collect()
    # Only the last source/dim pair (still on screen) may survive.
    alive = [r for r in refs[:-2] if r() is not None]
    assert not alive, f"{len(alive)} stale icons still cached"
