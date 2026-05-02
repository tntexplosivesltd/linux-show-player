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

from lisp.cues.cue import Cue


class TestCueColorName:
    def test_default_is_empty_string(self, mock_app):
        cue = Cue(mock_app)
        assert cue.color_name == ""

    def test_can_set_to_canonical_name(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = "Red"
        assert cue.color_name == "Red"

    def test_round_trips_through_properties(self, mock_app):
        cue = Cue(mock_app)
        cue.color_name = "Blue"
        props = cue.properties()
        assert props.get("color_name") == "Blue"

    def test_round_trips_through_update_properties(self, mock_app):
        cue = Cue(mock_app)
        cue.update_properties({"color_name": "Green"})
        assert cue.color_name == "Green"


class TestCueBackgroundHex:
    """Integration: cue_background_hex resolves correctly on real Cue
    objects (vs Task 4's tests which used MagicMock)."""

    def test_themed_takes_precedence(self, mock_app):
        from lisp.ui.themes import cue_background_hex
        from lisp.ui.themes.base import DEFAULT_CUE_PALETTE
        cue = Cue(mock_app)
        cue.color_name = "Red"
        cue.stylesheet = "background: #aabbcc"
        # Without applying any theme, falls back to DEFAULT_CUE_PALETTE
        assert cue_background_hex(cue) == DEFAULT_CUE_PALETTE["Red"]

    def test_legacy_hex_when_no_color_name(self, mock_app):
        from lisp.ui.themes import cue_background_hex
        cue = Cue(mock_app)
        cue.stylesheet = "background: #aabbcc"
        assert cue_background_hex(cue) == "#aabbcc"

    def test_empty_when_neither(self, mock_app):
        from lisp.ui.themes import cue_background_hex
        cue = Cue(mock_app)
        assert cue_background_hex(cue) == ""

    def test_legacy_hex_with_other_css(self, mock_app):
        """Other CSS keys don't affect the lookup — they coexist."""
        from lisp.ui.themes import cue_background_hex
        cue = Cue(mock_app)
        cue.stylesheet = "color: #fff; background: #aabbcc; font-size: 14px"
        assert cue_background_hex(cue) == "#aabbcc"
