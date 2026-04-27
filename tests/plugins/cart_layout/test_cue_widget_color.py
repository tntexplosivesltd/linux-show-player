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

"""Tests for cart-widget theme-aware stylesheet resolution.

Cart cues paint via Qt stylesheet. For themed cues (``color_name``
set), the resolved hex must be injected into the cue's stylesheet
``background`` key before the string is passed to ``setStyleSheet``.
Legacy custom-hex cues pass through unchanged."""

from lisp.cues.cue import Cue
from lisp.plugins.cart_layout.cue_widget import _resolve_cart_stylesheet
from lisp.ui.themes.base import DEFAULT_CUE_PALETTE
from lisp.ui.ui_utils import css_to_dict


class TestCartCueWidgetThemedColor:
    def test_themed_cue_injects_hex(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = "Red"
        cue.stylesheet = "color: #fff; font-size: 14px"
        result = _resolve_cart_stylesheet(cue)
        css = css_to_dict(result)
        assert css.get("background") == DEFAULT_CUE_PALETTE["Red"]
        # Other CSS properties preserved
        assert css.get("color") == "#fff"
        assert css.get("font-size") == "14px"

    def test_legacy_cue_uses_existing_stylesheet(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = ""
        cue.stylesheet = "background: #aabbcc"
        # Legacy hex is already in the stylesheet — pass through
        assert _resolve_cart_stylesheet(cue) == "background: #aabbcc"

    def test_no_color_no_background_key(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = ""
        cue.stylesheet = "color: #fff"
        # No themed name, no legacy bg — original stylesheet preserved
        assert _resolve_cart_stylesheet(cue) == "color: #fff"

    def test_themed_overrides_legacy_bg(self, mock_app):
        """If both color_name and stylesheet bg are set, themed wins
        (matches cue_background_hex precedence)."""
        cue = Cue(mock_app)
        cue.color_name = "Blue"
        cue.stylesheet = "background: #aabbcc"
        result = _resolve_cart_stylesheet(cue)
        css = css_to_dict(result)
        assert css.get("background") == DEFAULT_CUE_PALETTE["Blue"]
