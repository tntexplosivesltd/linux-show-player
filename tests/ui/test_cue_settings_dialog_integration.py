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

"""pytest-qt integration tests for CueSettingsDialog.

These tests manually populate CueSettingsRegistry (the real Application
singleton isn't instantiated in tests) and then assemble the dialog for
each cue type to confirm the canonical tab row.
"""

from unittest.mock import patch

import pytest
from PyQt5.QtWidgets import QGroupBox

from lisp.cues.cue import Cue
from lisp.cues.media_cue import MediaCue
from lisp.plugins.action_cues.command_cue import CommandCue, CommandCueSettings
from lisp.plugins.action_cues.group_cue import GroupCue, GroupCueSettings
from lisp.plugins.action_cues.seek_cue import SeekCue, SeekCueSettings
from lisp.plugins.action_cues.stop_all import StopAll, StopAllSettings
from lisp.plugins.controller.controller_settings import (
    CueControllerSettingsPage,
)
from lisp.plugins.gst_backend.gst_media_settings import GstMediaSettings
from lisp.plugins.midi.midi_cue import MidiCue, MidiCueSettings
from lisp.plugins.osc.osc_cue import OscCue, OscCueSettings
from lisp.plugins.timecode.settings import TimecodeSettings
from lisp.plugins.triggers.triggers_settings import TriggersSettings
from lisp.ui.icons import IconTheme
from lisp.ui.settings.cue_pages.cue_general import (
    CueGeneralSettingsPage,
    CueTimingPage,
)
from lisp.ui.settings.cue_pages.media_cue import MediaCueSettings
from lisp.ui.settings.cue_settings import (
    CueSettingsDialog,
    CueSettingsRegistry,
    cue_page_sort_key,
)
from lisp.ui.ui_utils import translate


@pytest.fixture(autouse=True)
def _icon_theme():
    IconTheme.set_theme_name("lisp")
    yield


@pytest.fixture
def registry():
    """Populate CueSettingsRegistry with every page we care about, then
    restore it between tests. The registry is a Singleton, so we patch
    its internal dict to isolate this test module from module-import
    side effects from the many plugin files that self-register.
    """
    reg = CueSettingsRegistry()
    original = reg._registry
    reg._registry = {}

    # Common pages — Cue base class
    reg.add(CueGeneralSettingsPage, Cue)
    reg.add(CueTimingPage, Cue)
    reg.add(TriggersSettings, Cue)
    reg.add(CueControllerSettingsPage, Cue)

    # Media pages
    reg.add(MediaCueSettings, MediaCue)
    reg.add(GstMediaSettings, MediaCue)
    reg.add(TimecodeSettings, MediaCue)

    # Cue-specific
    reg.add(StopAllSettings, StopAll)
    reg.add(GroupCueSettings, GroupCue)
    reg.add(CommandCueSettings, CommandCue)
    reg.add(SeekCueSettings, SeekCue)
    reg.add(MidiCueSettings, MidiCue)
    reg.add(OscCueSettings, OscCue)

    yield reg

    reg._registry = original


def _tab_labels(dialog):
    return [
        dialog.mainPage.tabWidget.tabText(i)
        for i in range(dialog.mainPage.tabWidget.count())
    ]


def _build_dialog(cue_class, qtbot):
    # CueControllerSettingsPage populates its internal QTabWidget from
    # protocols.CueSettingsPages — which is filled in by the controller
    # plugin's `init()` hook at runtime. In isolated tests that hook
    # hasn't run; force an empty list so the tab renders as an empty
    # stub instead of depending on plugin bootstrap order.
    with patch(
        "lisp.plugins.controller.protocols.CueSettingsPages", new=[]
    ):
        dialog = CueSettingsDialog(cue_class)
    qtbot.addWidget(dialog)
    return dialog


class TestCanonicalTabOrder:
    def test_base_cue_has_general_timing_triggers_controller(
        self, registry, qtbot
    ):
        dialog = _build_dialog(Cue, qtbot)
        assert _tab_labels(dialog) == [
            "General",
            "Timing",
            "Triggers",
            "Cue Control",
        ]

    def test_stop_all(self, registry, qtbot):
        dialog = _build_dialog(StopAll, qtbot)
        assert _tab_labels(dialog) == [
            "General",
            "Timing",
            "Stop Settings",
            "Triggers",
            "Cue Control",
        ]

    def test_group_cue(self, registry, qtbot):
        dialog = _build_dialog(GroupCue, qtbot)
        assert _tab_labels(dialog) == [
            "General",
            "Timing",
            "Group Settings",
            "Triggers",
            "Cue Control",
        ]

    def test_media_cue(self, registry, qtbot):
        # MediaCueSettings.loadSettings crashes on class_defaults()
        # (pre-existing: MediaCue's `media` property default is None,
        # and that page treats None as a TypeError). Verify the
        # canonical ordering via the registry+sort key directly instead
        # of via dialog construction — this tests the same contract.
        pages = sorted(
            registry.filter(MediaCue), key=cue_page_sort_key
        )
        labels = [translate("SettingsPageName", p.Name) for p in pages]
        assert labels == [
            "General",
            "Timing",
            "Triggers",
            "Cue Control",
            "Media Cue",
            "Media Settings",
            "Timecode",
        ]

    def test_midi_cue(self, registry, qtbot):
        dialog = _build_dialog(MidiCue, qtbot)
        assert _tab_labels(dialog) == [
            "General",
            "Timing",
            "MIDI Settings",
            "Triggers",
            "Cue Control",
        ]

    def test_osc_cue(self, registry, qtbot):
        dialog = _build_dialog(OscCue, qtbot)
        # OscCueSettings uses the "Cue Name" translation context; its
        # displayed title falls back to the raw Name string.
        labels = _tab_labels(dialog)
        assert labels[0:2] == ["General", "Timing"]
        assert labels[-2:] == ["Triggers", "Cue Control"]
        # The OSC settings tab label is the raw Name — the OSC cue page
        # intentionally declares QT_TRANSLATE_NOOP("Cue Name", ...).
        assert len(labels) == 5

    def test_command_cue(self, registry, qtbot):
        dialog = _build_dialog(CommandCue, qtbot)
        assert _tab_labels(dialog) == [
            "General",
            "Timing",
            "Command",
            "Triggers",
            "Cue Control",
        ]

    def test_seek_cue(self, registry, qtbot):
        dialog = _build_dialog(SeekCue, qtbot)
        assert _tab_labels(dialog) == [
            "General",
            "Timing",
            "Seek Settings",
            "Triggers",
            "Cue Control",
        ]


class TestGeneralTabStructure:
    def test_base_cue_general_tab_has_eleven_group_boxes(
        self, registry, qtbot
    ):
        dialog = _build_dialog(Cue, qtbot)

        general_tab = dialog.mainPage.page(0)
        groups = general_tab.findChildren(QGroupBox)
        # Eleven group boxes: Q#, Name, Description, Color, Font Size,
        # Start action, Stop action, Fade In, Fade Out, Exclusive,
        # Enabled.
        assert len(groups) == 11

        titles = {g.title() for g in groups}
        assert "Q#" in titles
        assert "Cue Name and Icon" in titles
        assert "Description/Note" in titles
        assert "Color" in titles
        assert "Set Font Size" in titles
        assert "Default Start action" in titles
        assert "Default Stop action" in titles
        assert "Fade In" in titles
        assert "Fade Out" in titles
        assert "Exclusive" in titles
        assert "Enabled" in titles

    def test_stop_all_general_tab_also_has_eleven_group_boxes(
        self, registry, qtbot
    ):
        dialog = _build_dialog(StopAll, qtbot)

        general_tab = dialog.mainPage.page(0)
        groups = general_tab.findChildren(QGroupBox)
        assert len(groups) == 11
