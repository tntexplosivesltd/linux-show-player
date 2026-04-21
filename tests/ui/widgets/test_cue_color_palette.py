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

from lisp.ui.widgets.cue_color_palette import (
    CueColorPalette,
    PALETTE,
    snap_to_palette,
)


class TestPaletteMetadata:
    """The module-level PALETTE is the single source of truth for swatch
    ordering and hex values — consumers (widget, inspector, E2E harness)
    all read it directly, so the invariants belong in one place."""

    def test_palette_has_seven_chromatic_entries(self):
        # 8 total UI slots but "None" is the empty string, not an entry.
        assert len(PALETTE) == 7

    def test_palette_names_match_agreed_order(self):
        names = [name for name, _ in PALETTE]
        assert names == [
            "Red", "Orange", "Yellow",
            "Green", "Blue", "Purple", "Grey",
        ]

    def test_palette_entries_are_uppercase_seven_char_hex(self):
        for _, hex_val in PALETTE:
            assert hex_val.startswith("#")
            assert len(hex_val) == 7
            assert hex_val == hex_val.upper()


class TestSnapToPalette:
    """snap_to_palette maps any hex to the nearest palette entry, or ""
    for the no-color slot. Used on load to migrate legacy custom colors
    to the strict palette without a session file rewrite."""

    def test_empty_string_returns_empty(self):
        assert snap_to_palette("") == ""

    def test_none_returns_empty(self):
        # css_to_dict may omit the "background" key entirely; callers
        # pass the .get() result straight through.
        assert snap_to_palette(None) == ""

    def test_malformed_hex_returns_empty(self):
        # Garbage is treated as "no color" rather than raising; matches
        # the existing permissiveness of css_to_dict.
        assert snap_to_palette("not-a-color") == ""
        assert snap_to_palette("#GGGGGG") == ""
        assert snap_to_palette("#12") == ""

    def test_exact_palette_match_preserved(self):
        assert snap_to_palette("#C03A2A") == "#C03A2A"

    def test_lowercase_match_normalized_to_uppercase(self):
        # Uppercase is the canonical storage form; normalising here
        # means downstream equality checks don't have to case-fold.
        assert snap_to_palette("#c03a2a") == "#C03A2A"

    def test_near_red_snaps_to_red(self):
        # One unit off each channel — red wins by a wide margin.
        assert snap_to_palette("#C13B2B") == "#C03A2A"

    def test_dark_red_snaps_to_red(self):
        # Deep red #700000 — RGB distance to red beats both grey and
        # orange, so it should land on red not on the neutrals.
        assert snap_to_palette("#700000") == "#C03A2A"

    def test_mid_grey_snaps_to_grey(self):
        assert snap_to_palette("#707070") == "#6E6E6E"


class TestCueColorPaletteCore:
    """CueColorPalette renders a one-row swatch picker: ``None`` first,
    then the 7 chromatic entries in PALETTE order. It owns the currently
    selected hex (``""`` for no colour) and emits ``colorPicked`` only
    on user interaction, never from the programmatic ``setColor``."""

    def test_constructs_with_none_selected(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        assert w.color() == ""

    def test_has_eight_swatches_in_agreed_order(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        swatches = w.swatches()
        assert len(swatches) == 8
        # None first, then 7 chromatic in palette order.
        assert [s.colorHex() for s in swatches] == [
            "", "#C03A2A", "#D6761E", "#C09A20",
            "#3E8A3B", "#3535B8", "#7848A6", "#6E6E6E",
        ]

    def test_set_color_with_palette_hex_round_trips(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("#C03A2A")
        assert w.color() == "#C03A2A"

    def test_set_color_with_non_palette_hex_snaps(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        # Legacy sessions store arbitrary hex; the widget must snap so
        # the inspector and storage stay within the palette contract.
        w.setColor("#C13B2B")
        assert w.color() == "#C03A2A"

    def test_set_color_with_empty_clears_to_none(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("#C03A2A")
        w.setColor("")
        assert w.color() == ""

    def test_set_color_is_silent(self, qtbot):
        # Programmatic setter must not emit — that signal is reserved
        # for user-initiated picks so the InspectorCommitEngine doesn't
        # treat a load-settings refresh as an edit.
        w = CueColorPalette()
        qtbot.addWidget(w)
        received = []
        w.colorPicked.connect(received.append)
        w.setColor("#C03A2A")
        w.setColor("")
        assert received == []

    def test_click_chromatic_swatch_emits_hex(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        red = w.swatches()[1]  # PALETTE[0] = Red, + 1 for the None slot
        with qtbot.waitSignal(w.colorPicked, timeout=500) as blocker:
            red.click()
        assert blocker.args == ["#C03A2A"]
        assert w.color() == "#C03A2A"

    def test_click_none_swatch_emits_empty(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("#C03A2A")  # start coloured so the click is a change
        none_swatch = w.swatches()[0]
        with qtbot.waitSignal(w.colorPicked, timeout=500) as blocker:
            none_swatch.click()
        assert blocker.args == [""]
        assert w.color() == ""

    def test_selection_follows_set_color(self, qtbot):
        # Exactly one swatch is visually selected; it matches color().
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("#3535B8")
        selected = [s for s in w.swatches() if s.isSelected()]
        assert len(selected) == 1
        assert selected[0].colorHex() == "#3535B8"

    def test_selection_on_none_when_empty(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        # Initial state has no colour — the None swatch should be the
        # visually selected one so the row always shows a selection.
        selected = [s for s in w.swatches() if s.isSelected()]
        assert len(selected) == 1
        assert selected[0].colorHex() == ""


class TestCueColorPaletteMixedState:
    """When the inspector shows multiple cues with divergent colours,
    the panel calls ``setMixed(True)`` on the widget. The palette must
    then render *no* swatch as selected — a blank row signals "values
    differ" without misleading the user about any single cue's colour.
    The first user click resolves divergence by selecting one palette
    entry, which implicitly clears mixed state."""

    def test_is_mixed_false_initially(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        assert w.isMixed() is False

    def test_set_mixed_true_clears_visible_selection(self, qtbot):
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("#C03A2A")
        w.setMixed(True)
        assert w.isMixed() is True
        # None of the swatches should render as selected while divergent.
        assert all(not s.isSelected() for s in w.swatches())

    def test_set_mixed_false_restores_selection(self, qtbot):
        # After dropping divergence flag, the selection should track the
        # stored colour again — the widget remembers what was set.
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("#3535B8")
        w.setMixed(True)
        w.setMixed(False)
        assert w.isMixed() is False
        selected = [s for s in w.swatches() if s.isSelected()]
        assert len(selected) == 1
        assert selected[0].colorHex() == "#3535B8"

    def test_color_preserved_through_mixed_cycle(self, qtbot):
        # setMixed must not disturb the underlying colour value —
        # only its visual presentation.
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setColor("#3E8A3B")
        w.setMixed(True)
        assert w.color() == "#3E8A3B"
        w.setMixed(False)
        assert w.color() == "#3E8A3B"

    def test_set_color_clears_mixed_state(self, qtbot):
        # A programmatic setColor is the panel's way of pushing a
        # definite value in — it should reset divergence.
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setMixed(True)
        w.setColor("#C03A2A")
        assert w.isMixed() is False
        selected = [s for s in w.swatches() if s.isSelected()]
        assert len(selected) == 1
        assert selected[0].colorHex() == "#C03A2A"

    def test_clicking_swatch_while_mixed_clears_mixed(self, qtbot):
        # User resolving divergence by picking a colour — mixed flag
        # must drop so the panel sees a real value next flush.
        w = CueColorPalette()
        qtbot.addWidget(w)
        w.setMixed(True)
        red = w.swatches()[1]
        with qtbot.waitSignal(w.colorPicked, timeout=500) as blocker:
            red.click()
        assert blocker.args == ["#C03A2A"]
        assert w.isMixed() is False
        assert w.color() == "#C03A2A"

    def test_set_mixed_is_silent(self, qtbot):
        # Mixed is purely a display hint — must not emit colorPicked,
        # or the commit engine will treat load-settings as an edit.
        w = CueColorPalette()
        qtbot.addWidget(w)
        received = []
        w.colorPicked.connect(received.append)
        w.setMixed(True)
        w.setMixed(False)
        assert received == []
