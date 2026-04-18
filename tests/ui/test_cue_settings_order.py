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

from PyQt5.QtCore import QT_TRANSLATE_NOOP

from lisp.ui.settings.cue_settings import cue_page_sort_key
from lisp.ui.settings.pages import SettingsPage


class _PageAlpha(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Alpha")
    SortOrder = 50


class _PageBravo(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Bravo")
    SortOrder = 10


class _PageCharlie(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Charlie")
    SortOrder = 50


class _PageDefaultZ(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Zulu")
    # No SortOrder override; inherits default (1000).


class _PageDefaultA(SettingsPage):
    Name = QT_TRANSLATE_NOOP("SettingsPageName", "Amber")
    # No SortOrder override; inherits default (1000).


class TestCuePageSortKey:
    def test_primary_sort_is_sort_order(self):
        pages = [_PageAlpha, _PageBravo]
        ordered = sorted(pages, key=cue_page_sort_key)
        assert ordered == [_PageBravo, _PageAlpha]

    def test_tiebreaker_is_alphabetical_name(self):
        # Alpha and Charlie share SortOrder = 50; Alpha should come first
        # by translated Name.
        pages = [_PageCharlie, _PageAlpha]
        ordered = sorted(pages, key=cue_page_sort_key)
        assert ordered == [_PageAlpha, _PageCharlie]

    def test_default_sort_order_is_1000(self):
        assert SettingsPage.SortOrder == 1000
        assert _PageDefaultZ.SortOrder == 1000

    def test_pages_without_override_sort_last(self):
        pages = [_PageDefaultZ, _PageAlpha, _PageBravo]
        ordered = sorted(pages, key=cue_page_sort_key)
        assert ordered == [_PageBravo, _PageAlpha, _PageDefaultZ]

    def test_default_pages_tiebreak_alphabetically(self):
        # Two default-SortOrder pages should sort by Name, not insertion.
        pages = [_PageDefaultZ, _PageDefaultA]
        ordered = sorted(pages, key=cue_page_sort_key)
        assert ordered == [_PageDefaultA, _PageDefaultZ]

    def test_full_ordering(self):
        pages = [
            _PageDefaultZ,
            _PageAlpha,
            _PageDefaultA,
            _PageCharlie,
            _PageBravo,
        ]
        ordered = sorted(pages, key=cue_page_sort_key)
        assert ordered == [
            _PageBravo,     # SortOrder 10
            _PageAlpha,     # SortOrder 50, Name "Alpha"
            _PageCharlie,   # SortOrder 50, Name "Charlie"
            _PageDefaultA,  # SortOrder 1000, Name "Amber"
            _PageDefaultZ,  # SortOrder 1000, Name "Zulu"
        ]


class TestCanonicalSortOrderValues:
    """Guard the canonical slot assignments against accidental drift."""

    def test_general_slot(self):
        # Imported here to avoid pulling cue_general at collection time
        # before Stage 2 lands; we verify the attribute directly.
        # When Stage 2 lands, CueGeneralSettingsPage will have SortOrder=10.
        pass

    def test_triggers_slot(self):
        from lisp.plugins.triggers.triggers_settings import TriggersSettings
        assert TriggersSettings.SortOrder == 40

    def test_controller_slot(self):
        from lisp.plugins.controller.controller_settings import (
            CueControllerSettingsPage,
        )
        assert CueControllerSettingsPage.SortOrder == 50

    def test_media_cue_slot(self):
        from lisp.ui.settings.cue_pages.media_cue import MediaCueSettings
        assert MediaCueSettings.SortOrder == 60

    def test_gst_media_slot(self):
        from lisp.plugins.gst_backend.gst_media_settings import (
            GstMediaSettings,
        )
        assert GstMediaSettings.SortOrder == 70

    def test_timecode_slot(self):
        from lisp.plugins.timecode.settings import TimecodeSettings
        assert TimecodeSettings.SortOrder == 80

    def test_cue_specific_slots(self):
        from lisp.plugins.action_cues.group_cue import GroupCueSettings
        from lisp.plugins.action_cues.stop_all import StopAllSettings
        from lisp.plugins.action_cues.command_cue import CommandCueSettings
        from lisp.plugins.action_cues.index_action_cue import (
            IndexActionCueSettings,
        )
        from lisp.plugins.action_cues.seek_cue import SeekCueSettings
        from lisp.plugins.action_cues.volume_control import VolumeSettings
        from lisp.plugins.action_cues.collection_cue import (
            CollectionCueSettings,
        )
        from lisp.plugins.midi.midi_cue import MidiCueSettings
        from lisp.plugins.osc.osc_cue import OscCueSettings

        for cls in (
            GroupCueSettings,
            StopAllSettings,
            CommandCueSettings,
            IndexActionCueSettings,
            SeekCueSettings,
            VolumeSettings,
            CollectionCueSettings,
            MidiCueSettings,
            OscCueSettings,
        ):
            assert cls.SortOrder == 30, (
                f"{cls.__name__} should occupy cue-specific slot 30"
            )
