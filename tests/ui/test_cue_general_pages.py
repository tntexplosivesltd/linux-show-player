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

import pytest

from lisp.cues.cue import Cue, CueAction
from lisp.cues.media_cue import MediaCue
from lisp.ui.icons import IconTheme
from lisp.ui.settings.cue_pages.cue_general import (
    CueGeneralSettingsPage,
    CueTimingPage,
)


@pytest.fixture(autouse=True)
def _icon_theme():
    """The cue-general page touches IconTheme.get when loadSettings is
    called with an ``icon`` key. Initialise a theme so the call doesn't
    explode on a None _GlobalTheme.
    """
    IconTheme.set_theme_name("lisp")
    yield


class _StubCueNoFades:
    """Cue type whose CueActions lack every fade variant."""

    CueActions = (CueAction.Start, CueAction.Stop)


class TestCueGeneralSettingsPageMetadata:
    def test_sort_order_slot(self):
        assert CueGeneralSettingsPage.SortOrder == 10

    def test_name_is_general(self):
        assert CueGeneralSettingsPage.Name == "General"


class TestCueTimingPageMetadata:
    def test_sort_order_slot(self):
        assert CueTimingPage.SortOrder == 20

    def test_name_is_timing(self):
        assert CueTimingPage.Name == "Timing"


class TestCueGeneralSettingsPageRoundTrip:
    """The merged General page must round-trip every key the four
    previous pages (Appearance + Behaviours + Fade + Exclusive) owned.

    Since the QLab palette swap, background colour is constrained to
    the fixed 7-entry palette (plus "no colour"), foreground colour
    has been dropped entirely, and legacy ``color:`` / unknown CSS
    keys drop on the next save rather than being preserved verbatim.
    """

    def test_round_trip_preserves_every_key(self, qtbot):
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)

        original = {
            "name": "My Cue",
            "icon": "audio",
            "description": "line1\nline2",
            # Palette hex (Red) so round-trip is exact; legacy "color:"
            # is intentionally still here to document the drop-on-save
            # migration path.
            "stylesheet": (
                "background:#C03A2A;color:#ffeedd;font-size:14pt;"
            ),
            "default_start_action": CueAction.FadeInStart.value,
            "default_stop_action": CueAction.FadeOutStop.value,
            "fadein_type": "Linear",
            "fadein_duration": 1.25,
            "fadeout_type": "Quadratic",
            "fadeout_duration": 2.5,
            "exclusive": True,
        }
        page.loadSettings(original)

        result = page.getSettings()

        assert result["name"] == "My Cue"
        assert result["icon"] == "audio"
        assert result["description"] == "line1\nline2"
        assert result["default_start_action"] == CueAction.FadeInStart.value
        assert result["default_stop_action"] == CueAction.FadeOutStop.value
        assert result["fadein_type"] == "Linear"
        assert result["fadein_duration"] == 1.25
        assert result["fadeout_type"] == "Quadratic"
        assert result["fadeout_duration"] == 2.5
        assert result["exclusive"] is True

        # Stylesheet is composed from the palette selector and font
        # spin; key order in the CSS string isn't guaranteed, so
        # decompose. Foreground color MUST be absent — the palette
        # only owns background, and unknown keys drop.
        css = result["stylesheet"]
        assert "font-size:14pt" in css
        assert "background:#C03A2A" in css
        assert "color:" not in css

    def test_legacy_non_palette_background_snaps_on_save(self, qtbot):
        # Sessions written before the palette existed may carry
        # arbitrary hex. loadSettings must snap to the nearest palette
        # entry so the very next save lands within the contract —
        # without this, legacy sessions silently produce non-palette
        # output that the inspector can't edit.
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)

        # #C13B2B is one unit off red on each channel — must snap to
        # the Red palette entry.
        page.loadSettings(
            {"stylesheet": "background:#C13B2B;font-size:12pt;"}
        )

        css = page.getSettings()["stylesheet"]
        assert "background:#C03A2A" in css

    def test_empty_load_does_not_crash(self, qtbot):
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)

        page.loadSettings({})
        # loadSettings({}) must not raise; getSettings still returns
        # the untouched widget state, which is always safe to inspect.
        page.getSettings()

    def test_stylesheet_without_font_size_loads_background(self, qtbot):
        # Palette hex round-trips exactly; legacy foreground color is
        # silently dropped because the palette doesn't own it.
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)

        page.loadSettings(
            {"stylesheet": "background:#3535B8;color:#040506;"}
        )

        css = page.getSettings().get("stylesheet", "")
        assert "background:#3535B8" in css
        assert "color:" not in css


class TestCueGeneralSettingsPageEnableCheck:
    """``enableCheck(True)`` switches groups into multi-edit mode — each
    group becomes checkable and initially unchecked, so its value is
    only included in getSettings if the user opts in by ticking the box.
    ``enableCheck(False)`` reverts to single-cue mode (always-include)."""

    def test_enable_check_true_makes_groups_checkable(self, qtbot):
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)
        page.loadSettings(
            {"name": "X", "exclusive": True, "description": "d"}
        )

        page.enableCheck(True)

        for group in (
            page.cueNameGroup,
            page.cueDescriptionGroup,
            page.colorGroup,
            page.fontSizeGroup,
            page.startActionGroup,
            page.stopActionGroup,
            page.fadeInGroup,
            page.fadeOutGroup,
            page.exclusiveGroup,
        ):
            assert group.isCheckable()
            assert not group.isChecked()

        # Unchecked groups filter their values out.
        assert page.getSettings() == {}

    def test_enable_check_false_disables_checkability(self, qtbot):
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)
        page.enableCheck(True)
        # Now revert
        page.enableCheck(False)

        for group in (
            page.cueNameGroup,
            page.cueDescriptionGroup,
            page.colorGroup,
            page.fontSizeGroup,
            page.startActionGroup,
            page.stopActionGroup,
            page.fadeInGroup,
            page.fadeOutGroup,
            page.exclusiveGroup,
        ):
            assert not group.isCheckable()


class TestCueGeneralColorGroupEmission:
    """Emitting a stylesheet when the colour group is ticked — even
    when the user picked "No color" — is the only way the diff engine
    can carry the clear across to the selected cues.

    Regression: prior to this coverage, ``getSettings`` skipped the
    ``stylesheet`` key entirely when the resulting style dict was
    empty, so "No color" in multi-select produced no diff and no
    ``UpdateCuesCommand`` — the clear was silently dropped.
    """

    def test_no_color_in_multi_edit_emits_empty_stylesheet(
        self, qtbot
    ):
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)
        page.enableCheck(True)

        # User ticks only the colour group, then picks "No color".
        page.colorGroup.setChecked(True)
        page.colorPalette.setColor("")

        settings = page.getSettings()

        # ``stylesheet`` must be present — otherwise ``_dict_diff``
        # treats the missing key as "no change" and the clear never
        # reaches the cues.
        assert "stylesheet" in settings
        assert "background" not in settings["stylesheet"]

    def test_no_color_with_font_size_also_ticked(self, qtbot):
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)
        page.enableCheck(True)

        page.colorGroup.setChecked(True)
        page.fontSizeGroup.setChecked(True)
        page.colorPalette.setColor("")
        page.fontSizeSpin.setValue(14)

        settings = page.getSettings()

        assert "stylesheet" in settings
        assert "background" not in settings["stylesheet"]
        assert "font-size:14pt" in settings["stylesheet"]

    def test_palette_color_in_multi_edit_emits_stylesheet(self, qtbot):
        """Sanity: picking a real palette colour also emits the key.

        This was already working pre-fix, but lock it in so the
        No-color fix doesn't overshoot and break the common case.
        """
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)
        page.enableCheck(True)

        page.colorGroup.setChecked(True)
        page.colorPalette.setColor("#3E8A3B")

        settings = page.getSettings()

        assert "stylesheet" in settings
        assert "background:#3E8A3B" in settings["stylesheet"]

    def test_color_group_unticked_still_omits_stylesheet(self, qtbot):
        """If the user hasn't ticked the colour or font groups, the
        stylesheet key must NOT appear — otherwise the diff engine
        would clear every cue's stylesheet just because the inspector
        was opened."""
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)
        page.enableCheck(True)

        settings = page.getSettings()

        assert "stylesheet" not in settings

    def test_font_size_spin_has_legible_minimum(self, qtbot):
        """QSpinBox defaults to a minimum of 0, which would let a
        user nudge the font size down to 0pt or round-trip a
        corrupted session that had ``font-size:0pt`` and render the
        cue name unreadable. Clamp to 6pt — below that Qt's default
        style can't realistically paint the list-layout text.
        """
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)

        assert page.fontSizeSpin.minimum() >= 6


class TestCueGeneralFadeGating:
    def test_fade_groups_disabled_when_actions_lack_fade(self, qtbot):
        page = CueGeneralSettingsPage(_StubCueNoFades)
        qtbot.addWidget(page)

        assert not page.fadeInGroup.isEnabled()
        assert not page.fadeOutGroup.isEnabled()

    def test_fade_groups_enabled_for_media_cue(self, qtbot):
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)

        assert page.fadeInGroup.isEnabled()
        assert page.fadeOutGroup.isEnabled()

    def test_base_cue_has_no_fade_groups(self, qtbot):
        page = CueGeneralSettingsPage(Cue)
        qtbot.addWidget(page)

        assert not page.fadeInGroup.isEnabled()
        assert not page.fadeOutGroup.isEnabled()

    def test_enable_check_does_not_re_enable_disabled_fade_groups(
        self, qtbot
    ):
        """Multi-edit mode (`enableCheck(True)`) must NOT re-enable fade
        groups that were construction-time disabled because the cue type
        lacks FadeInStart / FadeOutStop actions. ``setEnabled(False)``
        and ``setCheckable`` live on independent axes; a regression that
        reset one via the other would silently leak fade settings for
        cues that cannot actually fade."""
        page = CueGeneralSettingsPage(_StubCueNoFades)
        qtbot.addWidget(page)

        page.enableCheck(True)

        assert not page.fadeInGroup.isEnabled()
        assert not page.fadeOutGroup.isEnabled()
        # And getSettings must still exclude fade keys.
        result = page.getSettings()
        assert "fadein_type" not in result
        assert "fadein_duration" not in result
        assert "fadeout_type" not in result
        assert "fadeout_duration" not in result


class TestCueTimingPageRoundTrip:
    def test_round_trip_preserves_every_key(self, qtbot):
        page = CueTimingPage(MediaCue)
        qtbot.addWidget(page)

        original = {
            "pre_wait": 1.5,
            "post_wait": 3.25,
            "next_action": "DoNothing",
        }
        page.loadSettings(original)

        result = page.getSettings()
        assert result["pre_wait"] == 1.5
        assert result["post_wait"] == 3.25
        assert result["next_action"] == "DoNothing"

    def test_enable_check_true_makes_groups_checkable(self, qtbot):
        page = CueTimingPage(MediaCue)
        qtbot.addWidget(page)

        page.enableCheck(True)

        for group in (
            page.preWaitGroup,
            page.postWaitGroup,
            page.nextActionGroup,
        ):
            assert group.isCheckable()
            assert not group.isChecked()

        assert page.getSettings() == {}

    def test_enable_check_false_disables_checkability(self, qtbot):
        page = CueTimingPage(MediaCue)
        qtbot.addWidget(page)
        page.enableCheck(True)
        page.enableCheck(False)

        for group in (
            page.preWaitGroup,
            page.postWaitGroup,
            page.nextActionGroup,
        ):
            assert not group.isCheckable()

    def test_loads_zero_defaults_when_keys_missing(self, qtbot):
        page = CueTimingPage(MediaCue)
        qtbot.addWidget(page)

        page.loadSettings({})
        result = page.getSettings()

        assert result["pre_wait"] == 0
        assert result["post_wait"] == 0
