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

"""Unit tests for ``TrimmableWaveformWidget`` and ``TrimmableTimelineWidget``.

The trimmable widget overlays draggable start/stop markers on the
existing peak/RMS waveform. These tests exercise the widget in isolation
— a fake Waveform double avoids GStreamer, and the inspector page is
covered separately in ``tests/ui/test_media_cue_settings.py``.
"""

import pytest
from PyQt5.QtCore import Qt


class _FakeWaveform:
    """Stand-in for Waveform — no pipeline, no file I/O."""

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


class TestTrimmableWaveformWidgetDefaults:
    def test_initial_markers_span_full_duration(self, qtbot):
        """Fresh widget: start at 0, stop at duration.

        This is the "play to natural end" default users expect when
        opening a cue that was never trimmed.
        """
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=5_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        assert widget.startTime() == 0
        assert widget.stopTime() == 5_000

    def test_ready_updates_stop_to_duration(self, qtbot):
        """Late-arriving duration must update the stop marker.

        Real Waveforms are often constructed with ``duration=0`` and
        learn the real duration after the pipeline probes the file.
        """
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget

        waveform = _FakeWaveform(duration_ms=0)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        assert widget.stopTime() == 0  # initial snap

        waveform.duration = 8_000
        waveform.mark_ready()
        qtbot.wait(10)

        assert widget.stopTime() == 8_000


class TestTrimmableWaveformWidgetSetters:
    def test_set_start_clamps_to_valid_range(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        widget.setStartTime(-500)
        assert widget.startTime() == 0

        widget.setStartTime(20_000)
        assert widget.startTime() == widget.stopTime() - 1

    def test_set_stop_clamps_to_valid_range(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        widget.setStartTime(3_000)
        widget.setStopTime(1_000)
        assert widget.stopTime() == widget.startTime() + 1

        widget.setStopTime(999_999)
        assert widget.stopTime() == 10_000

    def test_set_start_emits_signal(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        with qtbot.waitSignal(widget.startTimeChanged, timeout=100) as blocker:
            widget.setStartTime(2_500)
        assert blocker.args == [2_500]

    def test_set_stop_emits_signal(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        with qtbot.waitSignal(widget.stopTimeChanged, timeout=100) as blocker:
            widget.setStopTime(7_500)
        assert blocker.args == [7_500]

    def test_silent_setters_suppress_emission(self, qtbot):
        from lisp.ui.widgets.waveform import TrimmableWaveformWidget
        waveform = _FakeWaveform(duration_ms=10_000)
        widget = TrimmableWaveformWidget(waveform)
        qtbot.addWidget(widget)

        emitted = []
        widget.startTimeChanged.connect(lambda v: emitted.append(v))
        widget.stopTimeChanged.connect(lambda v: emitted.append(v))

        widget.setStartTime(1_000, silent=True)
        widget.setStopTime(9_000, silent=True)

        assert emitted == []
        assert widget.startTime() == 1_000
        assert widget.stopTime() == 9_000
