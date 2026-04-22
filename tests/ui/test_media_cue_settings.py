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
