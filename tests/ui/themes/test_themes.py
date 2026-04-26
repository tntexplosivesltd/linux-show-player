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

import pytest
from PyQt5.QtGui import QColor, QPalette
from unittest.mock import MagicMock

from lisp.ui.themes.base import (
    CUE_COLOR_NAMES,
    DEFAULT_CUE_PALETTE,
    ThemeColors,
)


class TestThemeColorsValidation:
    def _base_kwargs(self):
        return dict(
            background=QColor(30, 30, 30),
            foreground=QColor(52, 52, 52),
            text=QColor(230, 230, 230),
            highlight=QColor(65, 155, 230),
        )

    def test_constructs_with_required_fields_only(self):
        c = ThemeColors(**self._base_kwargs())
        assert c.background == QColor(30, 30, 30)
        assert c.cue_palette == DEFAULT_CUE_PALETTE

    def test_canonical_names_are_seven(self):
        assert len(CUE_COLOR_NAMES) == 7
        assert set(CUE_COLOR_NAMES) == {
            "Red", "Orange", "Yellow",
            "Green", "Blue", "Purple", "Grey",
        }

    def test_default_palette_covers_all_names(self):
        assert set(DEFAULT_CUE_PALETTE.keys()) == set(CUE_COLOR_NAMES)

    def test_palette_missing_name_raises(self):
        bad = dict(DEFAULT_CUE_PALETTE)
        del bad["Yellow"]
        with pytest.raises(ValueError, match="cue_palette"):
            ThemeColors(**self._base_kwargs(), cue_palette=bad)

    def test_palette_extra_name_raises(self):
        bad = dict(DEFAULT_CUE_PALETTE)
        bad["Magenta"] = "#ff00ff"
        with pytest.raises(ValueError, match="cue_palette"):
            ThemeColors(**self._base_kwargs(), cue_palette=bad)

    def test_palette_malformed_hex_raises(self):
        bad = dict(DEFAULT_CUE_PALETTE)
        bad["Red"] = "red"  # CSS name, not a hex
        with pytest.raises(ValueError, match="hex"):
            ThemeColors(**self._base_kwargs(), cue_palette=bad)

    def test_palette_short_hex_raises(self):
        bad = dict(DEFAULT_CUE_PALETTE)
        bad["Red"] = "#abc"
        with pytest.raises(ValueError, match="hex"):
            ThemeColors(**self._base_kwargs(), cue_palette=bad)


class TestThemeColorsDerivations:
    """Optional fields derive sensible defaults from base colors."""

    def _theme(self, **overrides):
        kwargs = dict(
            background=QColor(30, 30, 30),
            foreground=QColor(52, 52, 52),
            text=QColor(230, 230, 230),
            highlight=QColor(65, 155, 230),
        )
        kwargs.update(overrides)
        return ThemeColors(**kwargs)

    def test_alternate_base_derives_from_foreground_darker(self):
        c = self._theme()
        assert c.resolved_alternate_base() == QColor(52, 52, 52).darker(125)

    def test_alternate_base_override_wins(self):
        c = self._theme(alternate_base=QColor(99, 99, 99))
        assert c.resolved_alternate_base() == QColor(99, 99, 99)

    def test_light_role_derives_lighter_160(self):
        c = self._theme()
        assert c.resolved_light() == QColor(52, 52, 52).lighter(160)

    def test_midlight_role_derives_lighter_125(self):
        c = self._theme()
        assert c.resolved_midlight() == QColor(52, 52, 52).lighter(125)

    def test_dark_role_derives_darker_150(self):
        c = self._theme()
        assert c.resolved_dark() == QColor(52, 52, 52).darker(150)

    def test_mid_role_derives_darker_125(self):
        c = self._theme()
        assert c.resolved_mid() == QColor(52, 52, 52).darker(125)

    def test_bright_text_default_is_pure_red(self):
        c = self._theme()
        assert c.resolved_bright_text() == QColor(255, 0, 0)

    def test_highlighted_text_default_is_black(self):
        c = self._theme()
        assert c.resolved_highlighted_text() == QColor(0, 0, 0)


class TestBaseThemeApply:
    """BaseTheme.apply maps ThemeColors to a QPalette on the QApplication."""

    def _make_dark_theme(self):
        from lisp.ui.themes.base import BaseTheme

        class _TestDark(BaseTheme):
            Colors = ThemeColors(
                background=QColor(30, 30, 30),
                foreground=QColor(52, 52, 52),
                text=QColor(230, 230, 230),
                highlight=QColor(65, 155, 230),
            )

        return _TestDark()

    def test_window_role_uses_foreground(self, qapp):
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert qapp.palette().color(QPalette.Window) == QColor(52, 52, 52)

    def test_base_role_uses_background(self, qapp):
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert qapp.palette().color(QPalette.Base) == QColor(30, 30, 30)

    def test_text_role_uses_text(self, qapp):
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert qapp.palette().color(QPalette.Text) == QColor(230, 230, 230)

    def test_highlight_role_uses_highlight(self, qapp):
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert qapp.palette().color(QPalette.Highlight) == QColor(65, 155, 230)

    def test_alternate_base_uses_derived_default(self, qapp):
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert qapp.palette().color(QPalette.AlternateBase) == \
            QColor(52, 52, 52).darker(125)

    def test_no_qss_when_qsspath_unset(self, qapp):
        theme = self._make_dark_theme()
        qapp.setStyleSheet("/* sentinel */")
        theme.apply(qapp)
        # QssPath is None, so apply should not touch the stylesheet
        assert qapp.styleSheet() == "/* sentinel */"

    def test_apply_sets_active_theme(self, qapp):
        from lisp.ui import themes
        theme = self._make_dark_theme()
        theme.apply(qapp)
        assert themes._active is theme


class TestCueColorHelpers:
    """Active-theme-aware lookups for cue colors."""

    def setup_method(self):
        from lisp.ui import themes
        themes._active = None  # reset between tests

    def test_cue_color_hex_returns_empty_for_empty(self):
        from lisp.ui.themes import cue_color_hex
        assert cue_color_hex("") == ""

    def test_cue_color_hex_no_active_theme_uses_default(self):
        from lisp.ui.themes import cue_color_hex
        assert cue_color_hex("Red") == DEFAULT_CUE_PALETTE["Red"]

    def test_cue_color_hex_uses_active_theme(self, qapp):
        from lisp.ui.themes import cue_color_hex
        from lisp.ui.themes.base import BaseTheme

        custom_palette = dict(DEFAULT_CUE_PALETTE)
        custom_palette["Red"] = "#dc322f"  # solarized red

        class _Solarized(BaseTheme):
            Colors = ThemeColors(
                background=QColor(253, 246, 227),
                foreground=QColor(238, 232, 213),
                text=QColor(101, 123, 131),
                highlight=QColor(38, 139, 210),
                cue_palette=custom_palette,
            )

        _Solarized().apply(qapp)
        assert cue_color_hex("Red") == "#dc322f"

    def test_cue_palette_returns_default_when_no_active(self):
        from lisp.ui.themes import cue_palette
        assert cue_palette() == DEFAULT_CUE_PALETTE

    def test_cue_background_hex_themed_takes_precedence(self):
        from lisp.ui.themes import cue_background_hex
        cue = MagicMock()
        cue.color_name = "Red"
        cue.stylesheet = "background: #aabbcc"
        assert cue_background_hex(cue) == DEFAULT_CUE_PALETTE["Red"]

    def test_cue_background_hex_falls_back_to_legacy_hex(self):
        from lisp.ui.themes import cue_background_hex
        cue = MagicMock()
        cue.color_name = ""
        cue.stylesheet = "background: #aabbcc"
        assert cue_background_hex(cue) == "#aabbcc"

    def test_cue_background_hex_returns_empty_when_no_color(self):
        from lisp.ui.themes import cue_background_hex
        cue = MagicMock()
        cue.color_name = ""
        cue.stylesheet = ""
        assert cue_background_hex(cue) == ""

    def test_cue_color_hex_unknown_name_returns_empty(self):
        """Hand-edited sessions or schema drift can produce unknown
        names. We must degrade gracefully, not raise — paint code
        depends on this."""
        from lisp.ui.themes import cue_color_hex
        assert cue_color_hex("Magenta") == ""
        assert cue_color_hex("NotAColor") == ""
