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
    previous pages (Appearance + Behaviours + Fade + Exclusive) owned."""

    def test_round_trip_preserves_every_key(self, qtbot):
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)

        original = {
            "name": "My Cue",
            "icon": "audio",
            "description": "line1\nline2",
            "stylesheet": (
                "background:#112233;color:#ffeedd;font-size:14pt;"
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

        # stylesheet is composed from the color buttons and the font spin;
        # key order in the CSS string isn't guaranteed, so decompose.
        css = result["stylesheet"]
        assert "font-size:14pt" in css
        assert "background:" in css
        assert "color:" in css

    def test_empty_load_does_not_crash(self, qtbot):
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)

        page.loadSettings({})
        # loadSettings({}) must not raise; getSettings still returns
        # the untouched widget state, which is always safe to inspect.
        page.getSettings()

    def test_stylesheet_without_font_size_loads_colors(self, qtbot):
        page = CueGeneralSettingsPage(MediaCue)
        qtbot.addWidget(page)

        page.loadSettings({"stylesheet": "background:#010203;color:#040506;"})

        css = page.getSettings().get("stylesheet", "")
        assert "background:#010203" in css
        assert "color:#040506" in css


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
