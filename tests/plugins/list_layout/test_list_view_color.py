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

from lisp.cues.cue import Cue
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
