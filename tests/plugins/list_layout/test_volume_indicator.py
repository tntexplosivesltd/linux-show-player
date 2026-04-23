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

"""Tests for the cue volume indicator label."""

import pytest

from lisp.plugins.list_layout.playing_widgets import _format_db_text


class TestFormatDbText:
    """`_format_db_text` maps a linear volume value to a display string.

    Formatting contract:
        - Unity  (1.0)      -> "+0.0 dB"
        - Below 1.0         -> "-N.N dB"   (negative sign)
        - Above 1.0         -> "+N.N dB"   (explicit plus sign)
        - At/below silence  -> "-∞ dB" (uses MIN_VOLUME_DB sentinel)
    """

    @pytest.mark.parametrize(
        "linear, expected",
        [
            (1.0, "+0.0 dB"),
            (0.5, "-6.0 dB"),
            (2.0, "+6.0 dB"),
            (10.0, "+20.0 dB"),
        ],
    )
    def test_ordinary_values(self, linear, expected):
        assert _format_db_text(linear) == expected

    def test_exact_zero_renders_minus_infinity(self):
        assert _format_db_text(0.0) == "-∞ dB"

    def test_below_min_volume_renders_minus_infinity(self):
        # MIN_VOLUME is ~6.3e-08; 1e-09 is well below.
        assert _format_db_text(1e-09) == "-∞ dB"

    def test_sign_prefix_anchors_digit_width(self):
        """Values just above and below unity share digit width thanks
        to the explicit +/- prefix, so the label does not shift
        horizontally by one character as volume crosses 0 dB.
        """
        assert len(_format_db_text(1.0)) == len(_format_db_text(0.999))
