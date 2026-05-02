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

"""Tests for cue color resolution at the list_view render site.

The actual render-time mutation of QBrush is exercised end-to-end by
running LiSP, but we can pin the *contract* that ``cue_background_hex``
behaves correctly when called with real ``Cue`` instances — the same
contract the render path now depends on."""

from unittest.mock import MagicMock, patch

import pytest
from PyQt5.QtGui import QColor

from lisp.cues.cue import Cue
from lisp.cues.cue_model import CueModel
from lisp.plugins.list_layout.list_view import CueListView
from lisp.plugins.list_layout.models import CueListModel
from lisp.ui.icons import IconTheme
from lisp.ui.themes import cue_background_hex
from lisp.ui.themes.base import DEFAULT_CUE_PALETTE


class TestListViewColorResolution:
    def test_themed_cue_uses_default_palette_hex_when_no_theme(
        self, mock_app
    ):
        """A cue with color_name='Red' resolves through cue_background_hex
        and (without an active theme) gets the DEFAULT_CUE_PALETTE hex."""
        cue = Cue(mock_app)
        cue.color_name = "Red"
        cue.stylesheet = ""
        assert cue_background_hex(cue) == DEFAULT_CUE_PALETTE["Red"]

    def test_legacy_cue_uses_stylesheet_hex(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = ""
        cue.stylesheet = "background: #aabbcc; font-size: 14px"
        assert cue_background_hex(cue) == "#aabbcc"

    def test_themed_takes_precedence_over_stylesheet(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = "Blue"
        cue.stylesheet = "background: #aabbcc"
        assert cue_background_hex(cue) == DEFAULT_CUE_PALETTE["Blue"]

    def test_no_color_returns_empty(self, mock_app):
        cue = Cue(mock_app)
        assert cue_background_hex(cue) == ""


@pytest.fixture(autouse=True)
def _icon_theme():
    """List-column widgets pull icons via IconTheme.get at construction
    time. Ensure a theme is set so CueListView can be instantiated."""
    if IconTheme._GlobalTheme is None:
        IconTheme.set_theme_name("lisp")
    yield


def _build_view_with_cue(mock_app):
    """Build a CueListView containing one Cue and return (view, item)."""
    cue_model = CueModel()
    list_model = CueListModel(cue_model)
    mock_app.cue_model = cue_model

    fake_app = MagicMock()
    fake_app.pre_arm_manager = None

    with patch(
        "lisp.plugins.list_layout.list_view.Application",
        return_value=fake_app,
    ):
        view = CueListView(list_model)

    cue = Cue(id="c1", app=mock_app)
    cue_model.add(cue)
    item = view.topLevelItem(0)
    return view, item


class TestStandbyBrushFromTheme:
    """The standby cue's row brush must be sourced from
    ``themes.standby_indicator()`` so each theme can override it.
    Phase-2 contract: ``CueListView`` no longer carries a hardcoded
    yellow class constant."""

    def setup_method(self):
        from lisp.ui import themes
        themes._active = None  # reset between tests

    def test_class_constant_removed(self):
        """The legacy ``ITEM_CURRENT_BG`` class constant must be gone.
        If it's still present, paint code is reading the hardcoded
        value and Solarized themes won't take effect."""
        assert not hasattr(CueListView, "ITEM_CURRENT_BG"), (
            "CueListView.ITEM_CURRENT_BG must be removed; the standby "
            "brush is now sourced from themes.standby_indicator()."
        )

    def test_standby_brush_uses_default_when_no_theme(
        self, qapp, mock_app
    ):
        """No active theme → standby brush is the legacy yellow."""
        from lisp.ui.themes import DEFAULT_STANDBY_INDICATOR

        view, item = _build_view_with_cue(mock_app)
        view.setCurrentItem(item)
        qapp.processEvents()

        assert item.background(0).color() == DEFAULT_STANDBY_INDICATOR

    def test_standby_brush_uses_active_theme_indicator(
        self, qapp, mock_app
    ):
        """Active theme with custom standby_indicator → that hex wins."""
        from lisp.ui.themes.base import BaseTheme, ThemeColors

        magenta = QColor(211, 54, 130, 100)

        class _FakeSolarized(BaseTheme):
            Colors = ThemeColors(
                background=QColor(0, 43, 54),
                foreground=QColor(7, 54, 66),
                text=QColor(131, 148, 150),
                highlight=QColor(42, 161, 152),
                standby_indicator=magenta,
            )

        _FakeSolarized().apply(qapp)

        view, item = _build_view_with_cue(mock_app)
        view.setCurrentItem(item)
        qapp.processEvents()

        assert item.background(0).color() == magenta

    def test_standby_brush_overrides_cue_color(
        self, qapp, mock_app
    ):
        """A coloured cue that becomes standby paints the standby
        brush, not the cue colour. This locks in the existing override
        behaviour at ``__updateItemStyle`` line 506-508."""
        from lisp.ui.themes import DEFAULT_STANDBY_INDICATOR

        view, item = _build_view_with_cue(mock_app)
        item.cue.color_name = "Red"
        view.setCurrentItem(item)
        qapp.processEvents()

        assert item.background(0).color() == DEFAULT_STANDBY_INDICATOR


class TestListViewLiveThemeSwitch:
    """When the active theme changes mid-session, every existing item's
    background brush must be recomputed against the new palette. The
    brush is cached on the QTreeWidgetItem at the moment of the last
    ``__updateItemStyle`` call, so without a live refresh the rows keep
    showing the *previous* theme's hex until they are otherwise touched
    (selection change, cue edit, etc.)."""

    def setup_method(self):
        from lisp.ui import themes
        themes._active = None

    def teardown_method(self):
        # Apply leaks _active across tests; reset so the next file
        # doesn't see this test's theme as the active one.
        from lisp.ui import themes
        themes._active = None

    def _make_theme_with_red(self, red_hex, alpha=100):
        from lisp.ui.themes.base import (
            BaseTheme,
            DEFAULT_CUE_PALETTE,
            ThemeColors,
        )

        palette = dict(DEFAULT_CUE_PALETTE)
        palette["Red"] = red_hex

        class _T(BaseTheme):
            Colors = ThemeColors(
                background=QColor(30, 30, 30),
                foreground=QColor(52, 52, 52),
                text=QColor(230, 230, 230),
                highlight=QColor(65, 155, 230),
                cue_palette=palette,
                cue_alpha=alpha,
            )

        return _T()

    def test_item_brush_refreshes_after_theme_swap(
        self, qapp, mock_app
    ):
        theme_a = self._make_theme_with_red("#aa0000", alpha=120)
        theme_b = self._make_theme_with_red("#00aa00", alpha=120)

        theme_a.apply(qapp)

        view, item = _build_view_with_cue(mock_app)
        item.cue.color_name = "Red"
        # Force initial style application via a non-current touch:
        # the model add already styles it once, but we re-trigger
        # explicitly to be safe.
        view.setCurrentItem(item)
        view.setCurrentItem(None)
        qapp.processEvents()

        before = item.background(0).color()
        # Sanity: item is painted with theme A's red.
        assert before.red() == 0xAA and before.green() == 0x00, (
            f"Pre-swap brush should be theme A red, got {before.getRgb()}"
        )

        # Swap themes — this fires theme_changed; the view should
        # re-style every item.
        theme_b.apply(qapp)
        qapp.processEvents()

        after = item.background(0).color()
        assert after.red() == 0x00 and after.green() == 0xAA, (
            f"Post-swap brush should be theme B red, got {after.getRgb()}"
        )

    def test_standby_brush_refreshes_after_theme_swap(
        self, qapp, mock_app
    ):
        """The current/standby item's brush is sourced from
        ``standby_indicator()``. After a theme swap that changes the
        indicator, the standby row must repaint."""
        from lisp.ui.themes.base import BaseTheme, ThemeColors

        class _ThemeYellow(BaseTheme):
            Colors = ThemeColors(
                background=QColor(30, 30, 30),
                foreground=QColor(52, 52, 52),
                text=QColor(230, 230, 230),
                highlight=QColor(65, 155, 230),
                standby_indicator=QColor(250, 220, 0, 100),
            )

        class _ThemeMagenta(BaseTheme):
            Colors = ThemeColors(
                background=QColor(30, 30, 30),
                foreground=QColor(52, 52, 52),
                text=QColor(230, 230, 230),
                highlight=QColor(65, 155, 230),
                standby_indicator=QColor(211, 54, 130, 180),
            )

        _ThemeYellow().apply(qapp)
        view, item = _build_view_with_cue(mock_app)
        view.setCurrentItem(item)
        qapp.processEvents()
        assert item.background(0).color() == QColor(250, 220, 0, 100)

        _ThemeMagenta().apply(qapp)
        qapp.processEvents()
        assert item.background(0).color() == QColor(211, 54, 130, 180)
