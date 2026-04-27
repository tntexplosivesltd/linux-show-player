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

from lisp.ui.themes.base import CUE_COLOR_NAMES
from lisp.ui.widgets.cue_color_palette import CueColorPalette


class TestCueColorPaletteCore:
    """CueColorPalette renders a one-row swatch picker: ``None`` first,
    then the 7 chromatic entries in CUE_COLOR_NAMES order. It owns the
    currently selected canonical name (``""`` for no colour) and emits
    ``colorPicked`` only on user interaction, never from the programmatic
    ``setColor``."""

    def test_has_eight_swatches_in_agreed_order(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        swatches = w.swatches()
        assert len(swatches) == 8
        # None first, then 7 chromatic in CUE_COLOR_NAMES order.
        assert [s.name() for s in swatches] == [
            "", "Red", "Orange", "Yellow",
            "Green", "Blue", "Purple", "Grey",
        ]

    def test_set_color_with_canonical_name_round_trips(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("Red")
        assert w.color() == "Red"

    def test_set_color_with_unknown_name_clears(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("Magenta")  # not a canonical name
        assert w.color() == ""

    def test_set_color_with_empty_clears_to_none(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("Red")
        w.setColor("")
        assert w.color() == ""

    def test_set_color_is_silent(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        received = []
        w.colorPicked.connect(received.append)
        w.setColor("Red")
        w.setColor("")
        assert received == []

    def test_click_chromatic_swatch_emits_name(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        red = w.swatches()[1]  # None at 0, then CUE_COLOR_NAMES[0] = Red
        with qtbot.waitSignal(w.colorPicked, timeout=500) as blocker:
            red.click()
        assert blocker.args == ["Red"]
        assert w.color() == "Red"

    def test_click_none_swatch_emits_empty(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("Red")
        none_swatch = w.swatches()[0]
        with qtbot.waitSignal(w.colorPicked, timeout=500) as blocker:
            none_swatch.click()
        assert blocker.args == [""]
        assert w.color() == ""

    def test_set_custom_hex_clears_swatches_and_records_hex(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setCustomHex("#aabbcc")
        assert w.color() == ""
        assert w.customHex() == "#AABBCC"
        # No swatch should claim selection.
        assert all(not s.isSelectedSwatch() for s in w.swatches())

    def test_set_custom_hex_invalid_clears(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setCustomHex("not a hex")
        assert w.customHex() == ""

    def test_clicking_swatch_after_custom_hex_graduates_to_themed(
        self, qtbot
    ):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setCustomHex("#aabbcc")
        red = w.swatches()[1]
        with qtbot.waitSignal(w.colorPicked, timeout=500):
            red.click()
        assert w.color() == "Red"
        assert w.customHex() == ""
