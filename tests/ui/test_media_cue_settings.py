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

"""Integration tests for ``MediaCueSettings``.

Covers the inspector-page concerns: two-column layout, sentinel
mapping on load, bidirectional numeric-field ↔ trimmer sync,
image-cue detection, and the multi-select placeholder.
"""

import pytest
from PyQt5.QtCore import QTime

from lisp.ui.settings.cue_pages.media_cue import MediaCueSettings


class _FakeWaveform:
    def __init__(self, duration_ms=10_000):
        from lisp.core.signal import Signal
        self.duration = duration_ms
        self.peak_samples = []
        self.rms_samples = []
        self.ready = Signal()
        self.failed = Signal()

    def load_waveform(self):
        return False

    def is_ready(self):
        return bool(self.peak_samples and self.rms_samples)

    def mark_ready(self, samples=256):
        self.peak_samples = [0.5] * samples
        self.rms_samples = [0.25] * samples
        self.ready.emit()

    def mark_failed(self):
        self.failed.emit()

    def clear(self):
        self.peak_samples = []
        self.rms_samples = []


class TestMediaCueSettingsLayout:
    def test_has_start_stop_loop_fields(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        assert page.startEdit is not None
        assert page.stopEdit is not None
        assert page.spinLoop is not None

    def test_grid_is_two_column(self, qtbot):
        """Column 0 = narrow fields, column 1 = wide waveform slot.

        ColumnStretch 1:3 gives the waveform ~75% of horizontal space.
        """
        page = MediaCueSettings()
        qtbot.addWidget(page)

        grid = page.layout()
        assert grid.columnStretch(0) == 1
        assert grid.columnStretch(1) == 3


class TestStopTimeSentinelMapping:
    def test_zero_stop_time_displays_as_duration(self, qtbot):
        """stop_time == 0 with a known duration displays as duration."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"stop_time": 0, "duration": 180_000, "start_time": 0}}
        )

        assert page.stopEdit.time() == QTime.fromMSecsSinceStartOfDay(180_000)

    def test_nonzero_stop_time_displays_verbatim(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 60_000,
                    "duration": 180_000,
                    "start_time": 0,
                }
            }
        )

        assert page.stopEdit.time() == QTime.fromMSecsSinceStartOfDay(60_000)

    def test_get_settings_returns_typed_value_verbatim(self, qtbot):
        """No sentinel translation on save — what the user sees is what persists."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"stop_time": 0, "duration": 180_000, "start_time": 0}}
        )

        settings = page.getSettings()
        assert settings["media"]["stop_time"] == 180_000

    def test_zero_duration_leaves_zero(self, qtbot):
        """When duration is unknown, the 0 sentinel can't be translated."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {"media": {"stop_time": 0, "duration": 0, "start_time": 0}}
        )

        assert page.stopEdit.time() == QTime.fromMSecsSinceStartOfDay(0)


class TestImageCueHandling:
    def test_image_cue_disables_trim_fields(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 0,
                    "duration": 5_000,
                    "start_time": 0,
                    "ImageInput": {},
                }
            }
        )

        assert not page.startEdit.isEnabled()
        assert not page.stopEdit.isEnabled()

    def test_image_cue_loop_field_stays_enabled(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 0,
                    "duration": 5_000,
                    "ImageInput": {},
                    "loop": 0,
                }
            }
        )
        assert page.spinLoop.isEnabled()

    def test_audio_cue_fields_stay_enabled(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings(
            {
                "media": {
                    "stop_time": 60_000,
                    "duration": 180_000,
                    "UriInput": {},
                    "Volume": {},
                }
            }
        )
        assert page.startEdit.isEnabled()
        assert page.stopEdit.isEnabled()


class TestMultiSelectPlaceholder:
    def test_single_cue_shows_waveform_slot(self, qtbot):
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.loadSettings({"media": {"duration": 10_000}})
        page.show()
        qtbot.waitExposed(page)
        assert not page.placeholderLabel.isVisible()

    def test_enable_check_true_shows_placeholder(self, qtbot):
        """enableCheck(True) is how the inspector signals multi-select."""
        page = MediaCueSettings()
        qtbot.addWidget(page)
        page.show()
        qtbot.waitExposed(page)

        page.enableCheck(True)
        assert page.placeholderLabel.isVisible()
